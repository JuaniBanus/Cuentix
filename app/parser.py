"""Interpretación de texto libre con Gemini.

Un mismo mensaje puede ser dos cosas distintas: un registro ("me gasté 8 lucas
en el super") o una pregunta ("¿cuánto gasté este mes?"). `interpretar_mensaje`
resuelve ambas en UNA sola llamada: el modelo devuelve la intención y, según
cuál sea, el movimiento a guardar o los filtros de la consulta.

Una sola llamada y no dos (clasificar → extraer) porque cuesta y tarda la
mitad, y porque el modelo decide la intención viendo el mensaje completo.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import GEMINI_API_KEY
from app.models import (
    Consulta,
    Intencion,
    Inversion,
    Moneda,
    Movimiento,
    TipoInversion,
    TipoMovimiento,
)

logger = logging.getLogger(__name__)

MODELO = "gemini-3.5-flash-lite"

# Cliente único a nivel módulo: reutiliza la conexión HTTP entre mensajes.
_cliente = genai.Client(api_key=GEMINI_API_KEY)


class ParserError(RuntimeError):
    """No se pudo interpretar el texto."""


# Los tres modelos siguientes son el esquema que le pedimos a Gemini. Son
# distintos de los de models.py a propósito:
#
# 1. El tipo Schema de la API de Gemini no acepta restricciones numéricas
#    (`gt` / `exclusiveMinimum`) ni el `anyOf` que Pydantic genera para
#    `Decimal`. Acá usamos `float` sin restricciones, y la validación fuerte
#    (monto > 0, decimales, longitudes) la aplica `Movimiento` al construir
#    el objeto final.
# 2. `descripcion` sí está, y es a propósito: antes guardábamos el mensaje
#    literal del usuario, y esa frase quedaba en la base para siempre sin que
#    nada la leyera. Ahora el modelo devuelve una etiqueta corta, que es la
#    parte útil sin arrastrar cómo lo escribió.
#
# Ojo: el docstring de una clase viajaría a la API como `description` del
# schema, por eso las notas van como comentario.
class _MovimientoExtraido(BaseModel):
    fecha: date
    tipo: TipoMovimiento
    monto: float
    moneda: Moneda = Moneda.ARS
    categoria: str
    descripcion: str
    # Opcional de verdad: el modelo tiene que poder no contestarla. Si fuera
    # `str` con default "", el schema la pediría igual y el modelo llenaría el
    # hueco con lo primero que le suene.
    cuenta: str | None = None
    # PARA QUÉ se aparta la plata, cuando el usuario nombra una meta. No es una
    # columna: es el texto con el que después se busca el objetivo.
    objetivo: str | None = None


class _ConsultaExtraida(BaseModel):
    desde: date | None = None
    hasta: date | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    etiqueta_periodo: str | None = None


# Todo opcional salvo el tipo: una compra mal contada ("compré bitcoin") tiene
# que poder volver con los huecos marcados, para preguntar en vez de inventar.
class _InversionExtraida(BaseModel):
    tipo: TipoInversion | None = None
    ticker: str | None = None
    nombre: str | None = None
    cantidad: float | None = None
    precio_compra: float | None = None
    moneda: Moneda | None = None
    fecha_compra: date | None = None
    sector: str | None = None


class _InterpretacionExtraida(BaseModel):
    intencion: Intencion
    movimiento: _MovimientoExtraido | None = None
    consulta: _ConsultaExtraida | None = None
    inversion: _InversionExtraida | None = None


class Interpretacion(NamedTuple):
    """Resultado de interpretar un mensaje: qué quiso hacer y con qué datos."""

    intencion: Intencion
    movimiento: Movimiento | None = None
    consulta: Consulta | None = None
    inversion: Inversion | None = None
    # A qué objetivo dijo el usuario que va el ahorro, con sus palabras. Viaja
    # aparte del Movimiento porque no es un dato de la tabla: es la pista para
    # buscar el objetivo, y puede no encontrar ninguno.
    objetivo: str | None = None
    # Campos que la compra necesita y el mensaje no traía. Si tiene algo,
    # `inversion` viene en None y hay que preguntar en vez de guardar.
    faltantes: tuple[str, ...] = ()


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _instruccion_sistema(hoy: date) -> str:
    """Prompt de sistema. Recibe la fecha para resolver referencias relativas."""
    ayer = hoy - timedelta(days=1)
    # `strftime('%A')` devolvería el día en inglés según el locale del proceso.
    dia = _DIAS[hoy.weekday()]
    inicio_mes = hoy.replace(day=1)
    return f"""\
Sos un asistente de finanzas personales. El usuario es argentino y escribe en
español rioplatense, de forma coloquial y abreviada.

Cada mensaje es una de dos cosas, y tu primera tarea es decidir cuál:

- REGISTRAR: el usuario está anotando algo que pasó.
  "me gasté 8 lucas en el super", "cobré el sueldo", "puse 500 dólares en cripto".
- CONSULTAR: el usuario pregunta por datos que ya cargó.
  "¿cuánto gasté este mes?", "cuánto llevo ahorrado", "en qué se me va la plata".

Señales de consulta: signos de pregunta, "cuánto", "cuánta", "qué", "cómo vengo",
"en qué", "mostrame", "decime", "total de", verbos en pretérito perfecto
compuesto sin un monto concreto. Si el mensaje trae un monto explícito, casi
siempre es un registro.

FECHA DE HOY: {hoy.isoformat()}, {dia}. Ayer fue {ayer.isoformat()}.
El mes en curso arranca el {inicio_mes.isoformat()}.

=========================== SI ES UN REGISTRO ===========================
Poné intencion="registrar" y completá "movimiento". Dejá "consulta" en null.

MONTOS
- Interpretá la jerga: luca=1.000, palo=1.000.000, gamba=100.
  "8 lucas" = 8000, "300 mil" = 300000, "un millón y medio" = 1500000,
  "2 palos" = 2000000.
- Formato argentino: el punto separa miles y la coma decimales.
  "15.340,50" = 15340.50. Devolvé un número plano, sin separadores ni símbolo.
- El monto es siempre positivo. El signo lo determina el campo "tipo".

MONEDA
- Si no se aclara, asumí ARS.
- Usá USD si se menciona: "dólares", "usd", "u$s", "verdes", "billetes", "blue",
  "mep". "Palos verdes" son millones de dólares.
- Usá EUR si se menciona: "euros", "eur", "€".
  "gasté 200 euros" -> 200 EUR. "€150" -> 150 EUR. "150 eur" -> 150 EUR.
- El símbolo "$" solo, sin más aclaración, es ARS: en Argentina "$" son pesos.
  Solo es USD si además dice "dólares", "verdes" o similar.
- La jerga de montos (luca, palo, gamba) vale para cualquier moneda:
  "2 lucas de euros" = 2000 EUR.

TIPO (elegí exactamente uno)
- gasto: plata que sale y no vuelve. Compras, servicios, comida, transporte,
  alquiler, impuestos, salidas.
- ingreso: plata que entra. Sueldo, cobros, ventas, honorarios.
- ahorro: plata que se guarda y sigue siendo tuya, sin riesgo. Plazo fijo,
  guardar en el cajón, pasar a la caja de ahorro, "aparté para".
- inversion: plata puesta a buscar rendimiento asumiendo riesgo. Comprar
  dólares, acciones, CEDEARs, cripto, fondos comunes, bonos.
Ante la duda entre ahorro e inversion, preguntate si puede perder valor:
si puede, es inversion.

FECHA
- Resolvé referencias relativas contra la FECHA DE HOY: "ayer", "anteayer",
  "el lunes" (el lunes más reciente ya pasado), "hace una semana",
  "el 3" (el día 3 del mes en curso, o del mes pasado si todavía no llegó).
- Si el mensaje no menciona fecha, usá la fecha de hoy.
- Nunca devuelvas una fecha futura.

CATEGORIA
- Una o dos palabras, en minúsculas, sin tildes ni signos.
- Reutilizá etiquetas comunes: supermercado, comida, transporte, alquiler,
  servicios, salud, educacion, ocio, ropa, sueldo, freelance, dolares,
  cripto, plazo fijo, otros.
- Si nada encaja, usá "otros".

CUENTA (dónde está la plata)
- Completala SOLO si el mensaje dice dónde quedó, de dónde salió o a dónde fue
  la plata: "guardé 50 lucas en el banco" -> banco, "aparté efectivo" ->
  efectivo, "lo puse en Mercado Pago" -> billetera virtual, "50 mil al cajón"
  -> efectivo.
- Si el mensaje NO lo dice, dejala en null. Nunca la deduzcas del tipo, de la
  categoría ni de lo habitual: un null es la respuesta correcta cuando el
  usuario no lo mencionó, y es mejor que un lugar inventado.
  "aparté 50 mil para el viaje" -> cuenta=null. "gasté 8 lucas en el super"
  -> cuenta=null.
- No la confundas con la categoría, que es PARA QUE es la plata:
  "puse 100 lucas en un plazo fijo del banco" -> categoria="plazo fijo",
  cuenta="banco". "hice un plazo fijo" -> categoria="plazo fijo", cuenta=null.
- Etiquetas preferidas: efectivo, banco, billetera virtual, caja de seguridad,
  broker, cripto. Si nombran una marca o un producto, usá la etiqueta general:
  mercado pago / ualá / prex / naranja x -> billetera virtual;
  caja de ahorro / cuenta sueldo / homebanking / nombre de un banco -> banco;
  binance / lemon / buenbit -> cripto; cocos / iol / balanz -> broker;
  el cajón / abajo del colchón / la lata -> efectivo.
- Si no encaja en ninguna, usá una o dos palabras en minúsculas y sin tildes.

OBJETIVO (para qué se aparta la plata)
- SOLO para tipo=ahorro, y solo si el mensaje nombra una meta concreta:
  "guardé 150 mil para el viaje a Europa" -> objetivo="viaje a Europa"
  "aparté 50 lucas para el auto" -> objetivo="auto"
  "puse 20 mil para la casa" -> objetivo="casa"
- Devolvé el nombre de la meta tal como la nombró el usuario, SIN "para",
  "el", "la" ni el verbo. No inventes ni completes: si dijo "el auto",
  poné "auto", no "auto nuevo".
- En cualquier otro caso, null. Que un gasto o un ingreso tengan un motivo no
  los convierte en un objetivo: "gasté 8 lucas en el super" -> null,
  "cobré el sueldo" -> null.
- Ahorrar sin decir para qué también es null: "aparté 50 lucas" -> null,
  "guardé plata en el banco" -> null.
- No lo confundas con la cuenta, que es DÓNDE está la plata:
  "guardé 50 mil en el banco para el viaje" -> cuenta="banco",
  objetivo="viaje".

DESCRIPCION
- Una etiqueta de 2 a 5 palabras que diga QUE se compró o de dónde salió la
  plata, para distinguir dos movimientos de la misma categoría el mismo día.
  "pancho y coca", "sueldo agosto", "nafta", "cena con amigos", "plazo fijo".
- En minúsculas, sin tildes ni signos. Máximo 60 caracteres.
- NO copies la frase del usuario ni la parafrasees entera: es una etiqueta,
  no un resumen. Nada de montos, fechas ni verbos conjugados.
- NO incluyas datos personales: ni nombres propios, ni apodos, ni direcciones,
  ni comentarios sobre personas. "el regalo para Sofía" -> "regalo".
  "le pagué a mi psicóloga" -> "sesion".
- Si el mensaje no dice qué fue, repetí la categoría.

====================== SI ES UNA COMPRA DE INVERSIÓN =====================
Poné intencion="registrar_inversion" y completá "inversion". El resto en null.

Esto es distinto de un movimiento de tipo "inversion". Un movimiento anota
que salió plata ("puse 500 dólares en cripto"). Una COMPRA anota qué activo
entró a la cartera, con cantidad y precio unitario, y por eso se puede seguir
su ganancia después. Elegí registrar_inversion cuando el mensaje nombra un
activo concreto Y una cantidad:
  "compré 10 CEDEARs de Apple a US$25"
  "invertí en 0.5 BTC a 60000 USD"
  "me compré 100 AL30 a 1200 pesos"

CAMPOS
- tipo: accion, etf, bono, cedear, fci, cripto o plazo_fijo.
  Un CEDEAR es un cedear aunque el subyacente sea una acción (Apple, Tesla).
  Bitcoin, ethereum, USDT y demás son cripto. AL30/GD30/BOPREAL son bonos.
- ticker: el símbolo en MAYÚSCULAS, sin espacios. Deducilo del nombre cuando
  sea inequívoco: Apple->AAPL, Bitcoin->BTC, Ethereum->ETH, Tesla->TSLA,
  Mercado Libre->MELI, Google->GOOGL, Amazon->AMZN, Microsoft->MSFT.
  Si no lo sabés con certeza, dejalo en null: es preferible vacío a inventado.
- nombre: cómo lo diría una persona ("Apple", "Bitcoin", "Plazo fijo Galicia").
- cantidad: cuántas unidades. Acepta decimales (0.5 BTC).
- precio_compra: precio por UNIDAD, no el total. "10 a US$25" -> 25, no 250.
  Si el mensaje da solo el total ("puse 250 dólares en 10 cedears"), dividí:
  250/10 = 25.
- moneda: del PRECIO. "US$25" o "25 dólares" -> USD. "1200 pesos" -> ARS.
  "€30" -> EUR. Si no se aclara y el activo es cripto o CEDEAR, asumí USD;
  si es un bono argentino o un plazo fijo, asumí ARS.
- fecha_compra: como en los movimientos. Sin fecha, la de hoy.
- sector: solo si el mensaje lo menciona; si no, null.

DATOS FALTANTES: NO LOS INVENTES
Si falta algo que no se puede deducir —típicamente el precio o la cantidad—,
igual poné intencion="registrar_inversion" y devolvé "inversion" con los
campos que sí tengas y los otros en null. Nunca rellenes un precio con una
cotización que creas saber ni una cantidad con un 1 por defecto: el sistema
se encarga de preguntar lo que falte.
Ejemplo: "compré bitcoin" -> tipo=cripto, ticker=BTC, nombre=Bitcoin,
cantidad=null, precio_compra=null.

=========================== SI ES UNA CONSULTA ==========================
Elegí la intención que corresponda, completá "consulta" y dejá
"movimiento" en null.

- total_por_tipo: cuánto suma una clase de movimiento.
  "¿cuánto gasté este mes?" -> tipo=gasto, desde={inicio_mes.isoformat()}, hasta={hoy.isoformat()}
  "¿cuánto llevo ahorrado en dólares?" -> tipo=ahorro, moneda=USD, sin fechas
  "¿cuánto cobré este año?" -> tipo=ingreso, desde={hoy.year}-01-01
- total_por_categoria: el desglose por rubro.
  "¿en qué se me va la plata?" -> tipo=gasto, período del mes en curso
  "¿cuánto gasté en supermercado?" -> tipo=gasto, categoria="supermercado"
- balance: cuánto entró menos cuánto salió.
  "¿cómo vengo este mes?", "¿me alcanzó?", "balance de julio"

FILTROS DE LA CONSULTA
- desde / hasta: rango de fechas en formato YYYY-MM-DD, ambos inclusive.
  Dejalos en null si la pregunta no acota el tiempo ("cuánto llevo ahorrado",
  "en total", "histórico"). NO inventes un rango si el usuario no lo pidió.
- Si la pregunta habla del mes sin aclarar cuál, usá el mes en curso.
- tipo, moneda, categoria: completalos solo si la pregunta los menciona.
  En null significa "sin filtrar por eso".
- etiqueta_periodo: cómo nombrar el período en la respuesta, en minúsculas.
  Ejemplos: "este mes", "en julio", "este año", "en total", "la semana pasada".

======================= SI NO ES NINGUNA DE LAS DOS =====================
Poné intencion="desconocida" con los dos objetos en null. Usalo para saludos,
charla suelta o mensajes que no se entienden. No fuerces un registro."""


# Lo que un modelo escribe cuando le pedimos null y contesta con palabras.
# Cualquiera de estas es un "no lo dijo", no el nombre de una cuenta.
_CUENTA_VACIA = frozenset(
    {
        "null",
        "none",
        "nada",
        "ninguna",
        "ninguno",
        "n/a",
        "na",
        "no aplica",
        "no especifica",
        "no especificado",
        "no especificada",
        "no menciona",
        "no mencionada",
        "sin especificar",
        "desconocida",
        "desconocido",
        "-",
    }
)


def _normalizar_cuenta(valor: str | None) -> str | None:
    """Deja la cuenta lista para guardar, o None si no hay nada que guardar.

    El prompt pide null cuando el usuario no dice dónde, pero un modelo a veces
    contesta "no especificado" en vez de un null de verdad. Eso entraría a la
    base como si fuera una cuenta más y ensuciaría cualquier agrupación futura,
    así que se filtra acá.
    """
    limpio = " ".join((valor or "").split()).lower()[:40].strip()
    if not limpio or limpio in _CUENTA_VACIA:
        return None
    return limpio


def _a_movimiento(extraido: _MovimientoExtraido) -> Movimiento:
    """Convierte la salida de Gemini en el Movimiento definitivo.

    No recibe el mensaje del usuario a propósito: la etiqueta la genera el
    modelo y el texto original no sale nunca de `interpretar_mensaje`.

    `Decimal(str(...))` y no `Decimal(float)`: convertir el float directo
    arrastraría la basura binaria (0.1 -> 0.1000000000000000055...).
    """
    try:
        monto = Decimal(str(extraido.monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ParserError(f"Gemini devolvió un monto inusable: {extraido.monto!r}") from exc

    categoria = extraido.categoria.strip().lower()

    # El prompt pide 2 a 5 palabras, pero es un pedido y no una garantía: si el
    # modelo se pasa de largo, recortamos en vez de dejar que Movimiento lance
    # ValidationError, porque eso costaría el movimiento entero. El split/join
    # colapsa saltos de línea y espacios repetidos.
    descripcion = " ".join(extraido.descripcion.split()).lower()[:60].strip()

    try:
        return Movimiento(
            fecha=extraido.fecha,
            tipo=extraido.tipo,
            monto=monto,
            moneda=extraido.moneda,
            categoria=categoria,
            # Si el modelo la devuelve vacía, la categoría es un detalle pobre
            # pero válido: mejor eso que perder el movimiento por un campo
            # que no se muestra en ninguna respuesta.
            descripcion=descripcion or categoria,
            cuenta=_normalizar_cuenta(extraido.cuenta),
        )
    except ValidationError as exc:
        # Típicamente: monto <= 0 o categoria vacía.
        raise ParserError(f"Gemini devolvió un movimiento inválido: {exc.errors()}") from exc


# Nombre técnico -> cómo pedírselo al usuario.
_ETIQUETA_FALTANTE = {
    "tipo": "qué tipo de activo es (acción, cedear, cripto, bono, fci, plazo fijo)",
    "nombre": "qué compraste",
    "cantidad": "cuántas unidades compraste",
    "precio_compra": "a qué precio por unidad",
}


def _decimal_limpio(valor: float) -> Decimal:
    """float -> Decimal sin ceros de relleno ni basura binaria.

    `Decimal(str(...))` y no `Decimal(float)`, que arrastraría la cola binaria
    a una columna de 8 decimales. El normalize saca los ceros sobrantes
    (10.0 -> 10) y el quantize deshace la notación científica que normalize
    produce con los enteros (10 -> 1E+1), que Postgres no debería tener que
    interpretar.
    """
    numero = Decimal(str(valor)).normalize()
    if numero == numero.to_integral_value():
        return numero.quantize(Decimal(1))
    return numero


def _a_inversion(
    extraida: _InversionExtraida | None, hoy: date
) -> tuple[Inversion | None, tuple[str, ...]]:
    """Arma la Inversion, o devuelve qué falta para poder armarla.

    Devuelve (inversion, faltantes). Si `faltantes` tiene algo, `inversion` es
    None: preferimos preguntar antes que guardar una tenencia a medias, que
    después arruinaría todos los cálculos de ganancia.
    """
    if extraida is None:
        return None, ("tipo", "nombre", "cantidad", "precio_compra")

    faltantes = [
        campo
        for campo in ("tipo", "nombre", "cantidad", "precio_compra")
        if getattr(extraida, campo) is None
    ]
    # Un precio de 0 solo tiene sentido en un plazo fijo o un airdrop; para el
    # resto es casi siempre el modelo rellenando un hueco.
    if (
        extraida.precio_compra == 0
        and extraida.tipo is not TipoInversion.PLAZO_FIJO
        and "precio_compra" not in faltantes
    ):
        faltantes.append("precio_compra")
    if extraida.cantidad is not None and extraida.cantidad <= 0:
        faltantes.append("cantidad")

    if faltantes:
        return None, tuple(dict.fromkeys(faltantes))

    ticker = (extraida.ticker or "").strip().upper().replace(" ", "") or None

    try:
        inversion = Inversion(
            tipo=extraida.tipo,
            ticker=ticker[:20] if ticker else None,
            nombre=" ".join(extraida.nombre.split())[:120],
            cantidad=_decimal_limpio(extraida.cantidad),
            precio_compra=_decimal_limpio(extraida.precio_compra),
            moneda=extraida.moneda or Moneda.USD,
            fecha_compra=extraida.fecha_compra or hoy,
            sector=(extraida.sector or "").strip()[:60] or None,
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        raise ParserError(f"Gemini devolvió una inversión inválida: {exc}") from exc

    return inversion, ()


def _a_consulta(extraida: _ConsultaExtraida | None) -> Consulta:
    """Normaliza los filtros de la consulta. Sin filtros = todo el historial."""
    if extraida is None:
        return Consulta()

    etiqueta = (extraida.etiqueta_periodo or "").strip().lower() or "en total"
    categoria = (extraida.categoria or "").strip().lower() or None

    desde, hasta = extraida.desde, extraida.hasta
    if desde and hasta and desde > hasta:  # el modelo los dio al revés
        desde, hasta = hasta, desde

    return Consulta(
        desde=desde,
        hasta=hasta,
        tipo=extraida.tipo,
        moneda=extraida.moneda,
        categoria=categoria,
        etiqueta_periodo=etiqueta,
    )


def interpretar_mensaje(texto: str, hoy: date | None = None) -> Interpretacion:
    """Decide si el mensaje es un registro o una consulta, y extrae sus datos.

    Args:
        texto: el mensaje tal cual lo escribió el usuario.
        hoy: fecha de referencia para las expresiones relativas. Por defecto,
            la fecha actual; se puede fijar para tests reproducibles.

    Raises:
        ParserError: si el texto está vacío, si la API falla o si la respuesta
            no llega a ser utilizable. Siempre con un mensaje legible.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ParserError("El mensaje está vacío, no hay nada que hacer.")

    hoy = hoy or date.today()

    try:
        respuesta = _cliente.models.generate_content(
            model=MODELO,
            contents=texto,
            config=types.GenerateContentConfig(
                system_instruction=_instruccion_sistema(hoy),
                response_mime_type="application/json",
                response_schema=_InterpretacionExtraida,
                temperature=0,  # extracción determinista, no queremos creatividad
                # El modelo razona por defecto; para esta tarea no aporta y
                # agrega latencia y costo en cada mensaje del bot.
                # Los Gemini 3.x usan thinking_level: pasarles el thinking_budget
                # de la generación 2.5 devuelve 400 INVALID_ARGUMENT.
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
    except genai_errors.APIError as exc:
        logger.exception("Falló la llamada a Gemini")
        raise ParserError(
            f"No pude contactar al servicio de interpretación (error {exc.code}). "
            "Probá de nuevo en un momento."
        ) from exc
    except Exception as exc:  # red caída, DNS, timeout, etc.
        logger.exception("Error inesperado llamando a Gemini")
        raise ParserError("No pude contactar al servicio de interpretación.") from exc

    extraida = respuesta.parsed
    if extraida is None:
        # Pasa si el modelo cortó por filtros de seguridad o devolvió JSON roto.
        crudo = (respuesta.text or "").strip()
        logger.warning("Gemini no devolvió un objeto parseable. Crudo: %r", crudo[:500])
        raise ParserError("No entendí el mensaje.")

    if extraida.intencion is Intencion.REGISTRAR:
        if extraida.movimiento is None:
            # Dijo "registrar" pero no mandó los datos: tratamos como no entendido.
            logger.warning("Intención registrar sin movimiento para %r", texto)
            raise ParserError("Dijo registrar pero no extrajo el movimiento.")
        mencion = " ".join((extraida.movimiento.objetivo or "").split()).strip()
        return Interpretacion(
            intencion=Intencion.REGISTRAR,
            movimiento=_a_movimiento(extraida.movimiento),
            # Solo tiene sentido para los ahorros; en el resto se descarta
            # aunque el modelo la haya completado.
            objetivo=mencion or None
            if extraida.movimiento.tipo is TipoMovimiento.AHORRO
            else None,
        )

    if extraida.intencion is Intencion.REGISTRAR_INVERSION:
        inversion, faltantes = _a_inversion(extraida.inversion, hoy)
        return Interpretacion(
            intencion=Intencion.REGISTRAR_INVERSION,
            inversion=inversion,
            faltantes=faltantes,
        )

    if extraida.intencion is Intencion.DESCONOCIDA:
        return Interpretacion(intencion=Intencion.DESCONOCIDA)

    return Interpretacion(
        intencion=extraida.intencion,
        consulta=_a_consulta(extraida.consulta),
    )


def parsear_movimiento(texto: str, hoy: date | None = None) -> Movimiento:
    """Interpreta el texto exigiendo que sea un registro.

    Se mantiene por comodidad y para los tests: es `interpretar_mensaje`
    cuando ya sabés que el mensaje es un movimiento.

    Raises:
        ParserError: además de los casos de `interpretar_mensaje`, si el
            mensaje resultó ser una consulta y no un registro.
    """
    resultado = interpretar_mensaje(texto, hoy)
    if resultado.movimiento is None:
        raise ParserError(
            f"El mensaje no es un registro, es {resultado.intencion.value!r}."
        )
    return resultado.movimiento
