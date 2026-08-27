"""«¿Me lo puedo comprar?»: análisis de una compra que todavía no pasó."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from app.db import movimientos_para_analisis, obtener_objetivos, total_imputado
from app.models import CompraHipotetica, Moneda, TipoMovimiento
from app.objetivos import progreso

logger = logging.getLogger(__name__)

DIAS_DE_HISTORIA = 60


class Analisis:
    """Todo lo que se pudo calcular sobre la compra. Los None son datos que no hay."""

    __slots__ = (
        "compra", "gastado_mes", "ingresos_mes", "balance_mes", "balance_despues",
        "promedio_diario", "dias_equivalentes", "gastado_en_rubro", "metas",
    )

    def __init__(self, compra: CompraHipotetica) -> None:
        self.compra = compra
        self.gastado_mes = Decimal("0")
        self.ingresos_mes = Decimal("0")
        self.balance_mes = Decimal("0")
        self.balance_despues = Decimal("0")
        self.promedio_diario: Decimal | None = None
        self.dias_equivalentes: Decimal | None = None
        self.gastado_en_rubro: Decimal | None = None
        self.metas: list[tuple[str, Decimal, Decimal | None, Decimal | None]] = []


def _suma(filas: list[dict], tipo: str, moneda: Moneda) -> Decimal:
    return sum(
        (Decimal(str(f["monto"])) for f in filas
         if f["tipo"] == tipo and f["moneda"] == moneda.value),
        Decimal("0"),
    )


def analizar(
    compra: CompraHipotetica, hoy: date | None = None, *, user_id: str
) -> Analisis:
    """Calcula el impacto de la compra sobre la situación actual."""
    hoy = hoy or date.today()
    analisis = Analisis(compra)
    moneda = compra.moneda

    inicio_mes = hoy.replace(day=1)
    desde_historia = hoy - timedelta(days=DIAS_DE_HISTORIA)

    filas = movimientos_para_analisis(
        user_id=user_id, desde=desde_historia, hasta=hoy, moneda=moneda
    )
    del_mes = [f for f in filas if f["fecha"] >= inicio_mes.isoformat()]

    analisis.gastado_mes = _suma(del_mes, TipoMovimiento.GASTO.value, moneda)
    analisis.ingresos_mes = _suma(del_mes, TipoMovimiento.INGRESO.value, moneda)
    analisis.balance_mes = analisis.ingresos_mes - analisis.gastado_mes
    analisis.balance_despues = analisis.balance_mes - compra.monto

    gastos_historia = _suma(filas, TipoMovimiento.GASTO.value, moneda)
    dias_reales = min(DIAS_DE_HISTORIA, (hoy - _primer_dia(filas, desde_historia)).days + 1)
    if gastos_historia > 0 and dias_reales > 0:
        analisis.promedio_diario = (gastos_historia / dias_reales).quantize(Decimal("0.01"))
        if analisis.promedio_diario > 0:
            analisis.dias_equivalentes = (compra.monto / analisis.promedio_diario).quantize(
                Decimal("0.1")
            )

    if compra.categoria:
        analisis.gastado_en_rubro = sum(
            (Decimal(str(f["monto"])) for f in del_mes
             if f["tipo"] == TipoMovimiento.GASTO.value
             and f["moneda"] == moneda.value
             and (f.get("categoria") or "") == compra.categoria),
            Decimal("0"),
        )

    analisis.metas = _impacto_en_metas(compra, filas, dias_reales, user_id)
    return analisis


def _primer_dia(filas: list[dict], por_defecto: date) -> date:
    """La fecha del movimiento más viejo de la ventana."""
    fechas = []
    for f in filas:
        try:
            fechas.append(date.fromisoformat(f["fecha"]))
        except (KeyError, ValueError):
            continue
    return min(fechas) if fechas else por_defecto


def _impacto_en_metas(
    compra: CompraHipotetica, filas: list[dict], dias: int, user_id: str
) -> list[tuple[str, Decimal, Decimal | None, Decimal | None]]:
    """Cuánto se atrasaría cada meta si esa plata no se ahorra."""
    try:
        objetivos = obtener_objetivos(user_id=user_id, solo_activos=True)
    except Exception:
        logger.exception("No pude leer los objetivos para el análisis")
        return []

    ahorrado_ventana = _suma(filas, TipoMovimiento.AHORRO.value, compra.moneda)
    ritmo_semanal = (
        (ahorrado_ventana / dias * 7).quantize(Decimal("0.01"))
        if dias > 0 and ahorrado_ventana > 0
        else None
    )

    metas = []
    for objetivo in objetivos:
        if objetivo.get("moneda") != compra.moneda.value:
            continue
        try:
            meta = Decimal(str(objetivo["monto_objetivo"]))
            aportado = total_imputado(objetivo["id"], compra.moneda, user_id=user_id)
        except Exception:
            logger.exception("No pude calcular el progreso de %s", objetivo.get("nombre"))
            continue

        _, falta, completo = progreso(aportado, meta)
        if completo:
            continue

        atraso = (
            (compra.monto / ritmo_semanal).quantize(Decimal("0.1"))
            if ritmo_semanal and ritmo_semanal > 0
            else None
        )
        metas.append((objetivo.get("nombre", "tu meta"), falta, ritmo_semanal, atraso))

    return metas[:3]


def _semanas(valor: Decimal) -> str:
    """0.4 -> "3 días" · 2.0 -> "2 semanas" · 1.0 -> "1 semana"."""
    if valor < Decimal("1"):
        dias = max(int((valor * 7).to_integral_value()), 1)
        return f"{dias} día{'' if dias == 1 else 's'}"
    entero = valor.quantize(Decimal("1"))
    return f"{entero} semana{'' if entero == 1 else 's'}"


def _dias(valor: Decimal) -> str:
    if valor < Decimal("1"):
        return "menos de un día"
    entero = int(valor.to_integral_value())
    return f"{entero} día{'' if entero == 1 else 's'}"


def redactar(analisis: Analisis, formatear_monto) -> str:
    """El mensaje que ve el usuario: los números, y después él decide."""
    compra = analisis.compra
    moneda = compra.moneda
    fmt = formatear_monto

    lineas = [f"🤔 {compra.que} por {fmt(compra.monto, moneda)}. Cómo venís:"]
    lineas.append("")

    lineas.append(f"Este mes llevás gastados {fmt(analisis.gastado_mes, moneda)}.")
    if analisis.ingresos_mes > 0:
        signo = "" if analisis.balance_despues >= 0 else " (en rojo)"
        lineas.append(
            f"Tu balance va {fmt(analisis.balance_mes, moneda)} y quedaría en "
            f"{fmt(analisis.balance_despues, moneda)}{signo}."
        )
    else:
        lineas.append(
            "No tengo ingresos cargados este mes, así que no puedo calcular el balance."
        )

    if analisis.dias_equivalentes is not None:
        lineas.append("")
        lineas.append(
            f"Equivale a {_dias(analisis.dias_equivalentes)} de tu gasto promedio "
            f"({fmt(analisis.promedio_diario, moneda)} por día)."
        )

    if analisis.gastado_en_rubro is not None and analisis.gastado_en_rubro > 0:
        lineas.append(
            f"En {compra.categoria} ya llevás {fmt(analisis.gastado_en_rubro, moneda)} este mes."
        )

    if analisis.metas:
        lineas.append("")
        for nombre, falta, ritmo, atraso in analisis.metas:
            if atraso is not None:
                lineas.append(
                    f"🎯 {nombre}: te faltan {fmt(falta, moneda)}. "
                    f"Al ritmo actual ({fmt(ritmo, moneda)} por semana), "
                    f"esto la atrasaría unas {_semanas(atraso)}."
                )
            else:
                lineas.append(
                    f"🎯 {nombre}: te faltan {fmt(falta, moneda)}. "
                    "Todavía no tengo ahorros cargados para estimar cuánto la atrasaría."
                )

    lineas.append("")
    lineas.append("Son los números. La decisión es tuya 🙂")
    lineas.append("Si al final lo comprás, decímelo y lo anoto.")

    return "\n".join(lineas)
