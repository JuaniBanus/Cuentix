"""Retos de ahorro: micro-desafíos sacados de los propios hábitos.

CÓMO SE ELIGE QUÉ PROPONER
No hay una lista de retos genéricos. La propuesta sale de lo que la persona
efectivamente gasta: se miran sus categorías de los últimos meses y se elige
una que sea FRECUENTE (aparece la mayoría de las semanas) y PRESCINDIBLE.

La segunda condición es la delicada. Proponer "una semana sin alquiler" es
absurdo, y "una semana sin remedios" es peor que absurdo. Hay una lista de
categorías que nunca se proponen, y ante la duda no se propone nada: un reto
tonto quema la función entera.

EL AHORRO ES UNA ESTIMACIÓN
"Ahorrás ~$15.000" sale de lo que gastó en ese rubro en semanas comparables.
No es una promesa, y el texto lo dice con el ~ y con la palabra "estimado".

CELEBRAR SIN EMPALAGAR
Al cumplirlo se felicita, y ahí sí corresponde: el usuario se propuso algo y
lo hizo. Pero al fallarlo NO se reta ni se consuela con condescendencia; se
informa el resultado y se ofrece seguir. Nadie quiere que una app le diga
"no pasa nada, la próxima será" cuando gastó $3.000 en un café.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

# Categorías que NUNCA se proponen para un reto. Proponer no gastar en salud o
# en el alquiler no es un desafío, es un mal consejo.
_INTOCABLES = frozenset({
    "salud", "medicamentos", "farmacia", "alquiler", "expensas", "servicios",
    "luz", "gas", "agua", "internet", "impuestos", "educacion", "colegio",
    "prepaga", "obra social", "seguro", "transporte", "supermercado",
})

# Semanas de historia que se miran para estimar el ahorro.
SEMANAS_HISTORIA = 8
# Mínimo de apariciones para considerar que el rubro es un hábito.
APARICIONES_MINIMAS = 3
# Debajo de esto el reto no vale la pena proponerlo.
AHORRO_MINIMO = Decimal("1000")

DURACION_DIAS = 7


class Propuesta:
    """Un reto sugerido, todavía no aceptado."""

    __slots__ = ("categoria", "ahorro_estimado", "moneda", "apariciones", "semanas")

    def __init__(self, categoria, ahorro_estimado, moneda, apariciones, semanas):
        self.categoria = categoria
        self.ahorro_estimado = ahorro_estimado
        self.moneda = moneda
        self.apariciones = apariciones
        self.semanas = semanas


def proponer(filas: list[dict], moneda: str, hoy: date | None = None) -> Propuesta | None:
    """El mejor reto para esta persona, o None si no hay ninguno sensato."""
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=SEMANAS_HISTORIA * 7)

    # (categoría) -> {semana: total}
    por_categoria: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    for fila in filas:
        if fila.get("tipo") != "gasto" or fila.get("moneda") != moneda:
            continue
        categoria = (fila.get("categoria") or "").strip().lower()
        if not categoria or categoria in _INTOCABLES:
            continue
        try:
            cuando = date.fromisoformat(fila["fecha"])
            monto = Decimal(str(fila["monto"]))
        except Exception:
            continue
        if cuando < desde or cuando > hoy or monto <= 0:
            continue
        semana = (cuando - desde).days // 7
        por_categoria[categoria][semana] += monto

    mejor: Propuesta | None = None

    for categoria, semanas in por_categoria.items():
        apariciones = len(semanas)
        if apariciones < APARICIONES_MINIMAS:
            continue  # no es un hábito, es una vez que pasó

        # El ahorro estimado es lo que gasta en una semana TÍPICA, no el
        # promedio: una semana con un gasto raro no puede inflar la promesa.
        totales = sorted(semanas.values())
        medio = len(totales) // 2
        tipico = (
            totales[medio] if len(totales) % 2
            else (totales[medio - 1] + totales[medio]) / 2
        ).quantize(Decimal("0.01"))

        if tipico < AHORRO_MINIMO:
            continue

        if mejor is None or tipico > mejor.ahorro_estimado:
            mejor = Propuesta(categoria, tipico, moneda, apariciones, len(semanas))

    return mejor


def revisar(reto: dict, gastado: Decimal, hoy: date | None = None) -> str | None:
    """El nuevo estado del reto, o None si sigue abierto.

    Se cierra por gasto (falló apenas se pasa) o por fecha (cumplió al
    terminar sin haberse pasado). Cerrar apenas falla y no al final es
    deliberado: enterarte el domingo de que lo perdiste el lunes no sirve.
    """
    hoy = hoy or date.today()

    try:
        hasta = date.fromisoformat(reto["hasta"])
    except Exception:
        return None

    if reto.get("tipo") == "tope":
        try:
            objetivo = Decimal(str(reto.get("objetivo") or 0))
        except Exception:
            objetivo = Decimal("0")
        if objetivo > 0 and gastado > objetivo:
            return "fallido"
    elif gastado > 0:
        return "fallido"

    return "cumplido" if hoy > hasta else None


# --------------------------------------------------------------------------
# Textos
# --------------------------------------------------------------------------


def texto_propuesta(propuesta: Propuesta, formatear_monto, moneda) -> str:
    return (
        f"🎯 Un reto para esta semana\n\n"
        f"Una semana sin gastar en {propuesta.categoria}.\n"
        f"Ahorrarías ~{formatear_monto(propuesta.ahorro_estimado, moneda)}, "
        f"que es lo que venís gastando en una semana típica "
        f"({propuesta.apariciones} de las últimas {SEMANAS_HISTORIA} semanas).\n\n"
        f"Es una estimación, no una promesa.\n"
        f"¿Le entrás? Contestame /acepto y lo arranco hoy mismo."
    )


def texto_aceptado(reto: dict, formatear_monto, moneda) -> str:
    return (
        f"💪 Arrancó: una semana sin {reto['categoria']}.\n"
        f"Termina el {date.fromisoformat(reto['hasta']).strftime('%d/%m')}.\n\n"
        "Yo llevo la cuenta: si registrás un gasto de ese rubro te aviso."
    )


def texto_cumplido(reto: dict, formatear_monto, moneda) -> str:
    ahorro = Decimal(str(reto.get("ahorro_estimado") or 0))
    return (
        f"🏆 ¡Lo lograste!\n\n"
        f"Una semana entera sin {reto['categoria']}. "
        f"Estimo que te ahorraste unos {formatear_monto(ahorro, moneda)}.\n\n"
        "¿Vamos por otro? /reto"
    )


def texto_fallido(reto: dict, gastado: Decimal, formatear_monto, moneda) -> str:
    """Informa el resultado. No reta y no consuela con condescendencia."""
    return (
        f"El reto de {reto['categoria']} se cortó acá: "
        f"registraste {formatear_monto(gastado, moneda)} del rubro.\n\n"
        "Si querés arrancar otro: /reto"
    )


def texto_activo(reto: dict, gastado: Decimal, formatear_monto, moneda) -> str:
    hasta = date.fromisoformat(reto["hasta"])
    faltan = (hasta - date.today()).days
    return (
        f"🎯 Reto activo: una semana sin {reto['categoria']}.\n"
        f"{'Termina hoy' if faltan <= 0 else f'Faltan {faltan} día' + ('' if faltan == 1 else 's')}.\n"
        f"Gastado del rubro hasta ahora: {formatear_monto(gastado, moneda)}."
    )


def texto_sin_propuesta() -> str:
    return (
        "Todavía no tengo suficiente historia para proponerte un reto que "
        "tenga sentido 🤔\n\n"
        "Necesito ver un rubro que gastes seguido y del que se pueda prescindir. "
        "Con algunas semanas más de movimientos cargados te propongo uno."
    )
