"""Retos de ahorro: micro-desafíos sacados de los propios hábitos."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

_INTOCABLES = frozenset({
    "salud", "medicamentos", "farmacia", "alquiler", "expensas", "servicios",
    "luz", "gas", "agua", "internet", "impuestos", "educacion", "colegio",
    "prepaga", "obra social", "seguro", "transporte", "supermercado",
})

SEMANAS_HISTORIA = 8
APARICIONES_MINIMAS = 3
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
            continue

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
    """El nuevo estado del reto, o None si sigue abierto."""
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
