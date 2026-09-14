"""Correcciones a un movimiento ya guardado, dichas en texto libre.

El usuario responde «eran 5 lucas» al mensaje con el que el bot confirmó un
gasto, y de ahí sale un update. Lo que este módulo hace es traducir esa frase a
un diccionario de campos para la base; quién es el dueño y a qué movimiento
apunta el reply ya se resolvieron antes de llegar acá.

Dos decisiones que valen la pena:

- Borrar se detecta sin Gemini. «borralo» es una lista corta y cerrada de
  frases, y no hace falta gastar una llamada para reconocerla. Además es la
  operación irreversible: conviene que dependa de una lista que se puede leer
  entera, y no de lo que interprete un modelo.
- La categoría vuelve a pasar por `Vocabulario.resolver()`, igual que al
  registrar. Corregir no es una puerta de atrás para meter una etiqueta que no
  está en la lista.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from google.genai import types
from pydantic import BaseModel

from app.categorias import Vocabulario
from app.models import Moneda, TipoMovimiento
from app.parser import ParserError, pedirle_a_gemini

logger = logging.getLogger(__name__)

# Los topes salen del modelo Movimiento: si allá cambian, acá tienen que
# cambiar igual, porque esto escribe en las mismas columnas.
TOPE_DESCRIPCION = 60
TOPE_COMERCIO = 60
TOPE_CUENTA = 40

_CENTAVOS = Decimal("0.01")

# Un movimiento no puede quedar en cero ni en un número absurdo. El tope es el
# mismo que acepta la columna (14 dígitos con 2 decimales).
MONTO_MAXIMO = Decimal("999999999999.99")

FRASES_BORRAR = frozenset({
    "borralo", "borrá", "borra", "borralo por favor", "borrar",
    "borra esto", "borrá esto", "borralo esto", "borrame esto",
    "eliminalo", "eliminá esto", "elimina esto", "eliminar", "eliminá",
    "sacalo", "sacá esto", "saca esto", "quitalo", "quitá esto",
    "anulalo", "anulá esto", "cancelalo", "cancelá esto",
    "no va", "no iba", "esto no va", "borra ese", "borralo ese",
    "deshacelo", "deshacé esto", "eliminá el movimiento",
    "borrá el movimiento", "borra el movimiento",
})


class Edicion(NamedTuple):
    """Qué hacer con el movimiento al que el usuario le respondió."""

    cambios: dict[str, Any]
    borrar: bool = False

    @property
    def hay_algo(self) -> bool:
        return self.borrar or bool(self.cambios)


def quiere_borrar(texto: str) -> bool:
    """Si la corrección es «borralo», sin preguntarle a nadie."""
    limpio = " ".join((texto or "").split()).strip().lower()
    limpio = limpio.strip(".,;:!¡?¿ ")
    return limpio in FRASES_BORRAR


class _EdicionExtraida(BaseModel):
    """Solo los campos que el usuario quiso cambiar; el resto queda en null."""

    monto: float | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    # Una de las categorías de la lista, o null si ninguna encaja. Lo que llegue
    # pasa igual por Vocabulario.resolver().
    categoria: str | None = None
    fecha: date | None = None
    descripcion: str | None = None
    comercio: str | None = None
    cuenta: str | None = None


def _instruccion(movimiento: dict, vocabulario: Vocabulario, hoy: date) -> str:
    """El prompt: qué movimiento es, cómo está hoy, y qué se puede tocar."""
    tipo_actual = str(movimiento.get("tipo") or "gasto")
    listado = vocabulario.para_prompt() if vocabulario else "(sin lista: dejá categoria en null)"

    return f"""\
El usuario está CORRIGIENDO un movimiento que ya está guardado. Respondió al
mensaje con el que se lo confirmaste y dijo qué estaba mal.

HOY ES {hoy:%Y-%m-%d} ({hoy:%A}).

EL MOVIMIENTO, COMO ESTA GUARDADO AHORA
- tipo: {tipo_actual}
- monto: {movimiento.get('monto')} {movimiento.get('moneda') or 'ARS'}
- categoria: {movimiento.get('categoria')}
- fecha: {movimiento.get('fecha')}
- descripcion: {movimiento.get('descripcion')}
- comercio: {movimiento.get('comercio')}
- cuenta: {movimiento.get('cuenta')}

TU TRABAJO
Devolvés SOLO los campos que el usuario quiere cambiar. Todo lo que no
mencionó va en null. Si dice «eran 5 lucas», cambia el monto y nada más: no
repitas la categoría ni la fecha porque ya están bien.

MONTOS
- "luca" = mil pesos. "5 lucas" = 5000. "15 mil" = 15000. "2 palos" = 2000000.
- El monto siempre es positivo, incluso si dice "sacale 2 mil": lo que devolvés
  es cuánto tiene que quedar, no la diferencia.

FECHAS
- "ayer", "anteayer", "el lunes", "el 3": convertilas a fecha real contra HOY.
- Nunca devuelvas una fecha futura: si la cuenta da adelante, es del año o del
  mes pasado.

TIPO
- Los tipos son: gasto, ingreso, ahorro, inversion.
- "no, fue ingreso" cambia el tipo. Ojo que al cambiar de tipo la categoría
  puede dejar de existir: si el usuario no dijo otra, dejá categoria en null y
  el código se encarga.

CATEGORIAS DISPONIBLES
{listado}
Elegí una de esa lista, exactamente como está escrita. Si ninguna encaja o el
usuario no habló de la categoría, dejá null.

SI NO ENTENDES QUE QUIERE CAMBIAR
Devolvé todo en null. Es correcto y esperable: mejor que el bot pregunte a que
invente un cambio que el usuario no pidió.
"""


def interpretar_correccion(
    texto: str,
    movimiento: dict,
    vocabulario: Vocabulario,
    hoy: date | None = None,
) -> Edicion:
    """Traduce «eran 5 lucas» a los campos que hay que actualizar.

    Devuelve una Edicion sin cambios cuando no se entendió qué corregir, que no
    es un error: quien llama se lo pregunta al usuario.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ParserError("La corrección está vacía.")

    if quiere_borrar(texto):
        return Edicion(cambios={}, borrar=True)

    hoy = hoy or date.today()

    config = types.GenerateContentConfig(
        system_instruction=_instruccion(movimiento, vocabulario, hoy),
        response_mime_type="application/json",
        response_schema=_EdicionExtraida,
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
    )

    respuesta = pedirle_a_gemini(texto, config)

    extraida = respuesta.parsed
    if extraida is None:
        crudo = (respuesta.text or "").strip()
        logger.warning("Gemini no devolvió una corrección parseable: %r", crudo[:300])
        raise ParserError("No entendí la corrección.")

    return _a_edicion(extraida, movimiento, vocabulario, hoy)


def _a_edicion(
    extraida: _EdicionExtraida,
    movimiento: dict,
    vocabulario: Vocabulario,
    hoy: date,
) -> Edicion:
    """Valida lo que devolvió el modelo y lo deja listo para la base."""
    cambios: dict[str, Any] = {}

    monto = _monto_valido(extraida.monto)
    if monto is not None and str(monto) != str(_decimal_o_none(movimiento.get("monto"))):
        cambios["monto"] = str(monto)

    if extraida.moneda is not None and extraida.moneda.value != movimiento.get("moneda"):
        cambios["moneda"] = extraida.moneda.value

    if extraida.fecha is not None:
        fecha = min(extraida.fecha, hoy)
        if fecha.isoformat() != str(movimiento.get("fecha")):
            cambios["fecha"] = fecha.isoformat()

    for campo, tope in (
        ("descripcion", TOPE_DESCRIPCION),
        ("comercio", TOPE_COMERCIO),
        ("cuenta", TOPE_CUENTA),
    ):
        valor = _texto_valido(getattr(extraida, campo), tope)
        if valor is not None and valor != movimiento.get(campo):
            cambios[campo] = valor

    # El tipo y la categoría se deciden juntos: una categoría solo existe
    # dentro de un tipo, así que cambiar el tipo puede dejar la etiqueta
    # colgada aunque el usuario no la haya nombrado.
    tipo_actual = _tipo_de(movimiento.get("tipo"))
    tipo_final = extraida.tipo or tipo_actual

    if extraida.tipo is not None and extraida.tipo is not tipo_actual:
        cambios["tipo"] = extraida.tipo.value

    categoria = _categoria_valida(
        extraida.categoria, tipo_final, vocabulario, movimiento, cambiando_tipo=
        extraida.tipo is not None and extraida.tipo is not tipo_actual,
    )
    if categoria is not None and categoria != movimiento.get("categoria"):
        cambios["categoria"] = categoria

    return Edicion(cambios=cambios, borrar=False)


def _tipo_de(valor: Any) -> TipoMovimiento:
    """El tipo guardado, o gasto si la fila trae algo raro."""
    try:
        return TipoMovimiento(str(valor))
    except ValueError:
        logger.warning("Movimiento con tipo desconocido: %r", valor)
        return TipoMovimiento.GASTO


def _decimal_o_none(valor: Any) -> Decimal | None:
    try:
        return Decimal(str(valor)).quantize(_CENTAVOS)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _monto_valido(valor: float | None) -> Decimal | None:
    """El monto corregido, o None si no vino o no sirve."""
    if valor is None:
        return None
    try:
        monto = Decimal(str(valor)).quantize(_CENTAVOS)
    except (InvalidOperation, ValueError):
        logger.info("Monto ilegible en la corrección: %r", valor)
        return None

    if monto <= 0 or monto > MONTO_MAXIMO:
        logger.info("Monto fuera de rango en la corrección: %s", monto)
        return None
    return monto


def _texto_valido(valor: str | None, tope: int) -> str | None:
    """Un texto libre limpio y acotado, o None si quedó vacío."""
    if valor is None:
        return None
    limpio = " ".join(str(valor).split()).strip()
    if not limpio:
        return None
    return limpio[:tope]


def _categoria_valida(
    nombre: str | None,
    tipo: TipoMovimiento,
    vocabulario: Vocabulario,
    movimiento: dict,
    *,
    cambiando_tipo: bool,
) -> str | None:
    """La categoría final, siempre dentro de la lista del usuario.

    Devuelve None cuando no hay nada que cambiar. Cuando cambia el tipo y la
    etiqueta vieja no existe en el tipo nuevo, cae en «otros» de ese tipo: es
    preferible a dejar un ingreso categorizado como «nafta».
    """
    if not vocabulario:
        # Sin lista (falta correr 019) no hay garantía que aplicar, así que no
        # se toca la categoría: se deja la que tenía.
        return None

    if nombre:
        elegida = vocabulario.resolver(nombre, tipo)
        if elegida is not None:
            return elegida.nombre
        logger.info("La corrección pidió una categoría que no existe: %r", nombre)
        # Si además cambió el tipo, hay que resolver igual más abajo.
        if not cambiando_tipo:
            return None

    if not cambiando_tipo:
        return None

    vieja = str(movimiento.get("categoria") or "")
    sigue_valiendo = vocabulario.resolver(vieja, tipo)
    if sigue_valiendo is not None:
        return sigue_valiendo.nombre

    return vocabulario.otros(tipo)
