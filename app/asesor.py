"""«¿Me lo puedo comprar?»: análisis de una compra que todavía no pasó.

QUÉ HACE Y QUÉ NO HACE

No registra nada. No recomienda. No dice "no te lo compres" ni "date el gusto".
Devuelve los números que el usuario ya tiene y que no está mirando, y se
aparta: cuánto lleva gastado, cómo le quedaría el balance, a cuántos días de
su promedio equivale eso, y qué le pasa a sus metas de ahorro.

El tono es una decisión de diseño, no un adorno. Un bot de finanzas que reta
se deja de usar en dos semanas, y el que deja de usarse no sirve para nada. Un
gasto grande puede ser perfectamente sensato —una heladera que se rompió, un
regalo, un viaje esperado diez años— y el bot no tiene forma de saberlo. Por
eso informa y cierra devolviendo la decisión, sin adjetivos sobre la compra ni
sobre quien la hace.

De ahí que no haya ningún umbral tipo "si supera el 30% del ingreso, avisar".
Un umbral es un juicio disfrazado de cálculo.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from app.db import movimientos_para_analisis, obtener_objetivos, total_imputado
from app.models import CompraHipotetica, Moneda, TipoMovimiento
from app.objetivos import progreso

logger = logging.getLogger(__name__)

# Ventana para el promedio diario y el ritmo de ahorro. Dos meses: un mes solo
# se deforma con cualquier gasto raro, y seis arrastran hábitos que ya cambiaron.
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
        # [(nombre, falta, ritmo_semanal, semanas_de_atraso)]
        self.metas: list[tuple[str, Decimal, Decimal | None, Decimal | None]] = []


def _suma(filas: list[dict], tipo: str, moneda: Moneda) -> Decimal:
    return sum(
        (Decimal(str(f["monto"])) for f in filas
         if f["tipo"] == tipo and f["moneda"] == moneda.value),
        Decimal("0"),
    )


def analizar(compra: CompraHipotetica, hoy: date | None = None) -> Analisis:
    """Calcula el impacto de la compra sobre la situación actual.

    Todo se mide en la moneda de la compra: mezclar pesos con dólares para
    decir "te quedarían X" daría un número que no existe.
    """
    hoy = hoy or date.today()
    analisis = Analisis(compra)
    moneda = compra.moneda

    inicio_mes = hoy.replace(day=1)
    desde_historia = hoy - timedelta(days=DIAS_DE_HISTORIA)

    # Una sola lectura para las dos ventanas: el mes está contenido en los 60
    # días, así que pedir dos veces sería pagar dos viajes por lo mismo.
    filas = movimientos_para_analisis(desde=desde_historia, hasta=hoy, moneda=moneda)
    del_mes = [f for f in filas if f["fecha"] >= inicio_mes.isoformat()]

    analisis.gastado_mes = _suma(del_mes, TipoMovimiento.GASTO.value, moneda)
    analisis.ingresos_mes = _suma(del_mes, TipoMovimiento.INGRESO.value, moneda)
    analisis.balance_mes = analisis.ingresos_mes - analisis.gastado_mes
    analisis.balance_despues = analisis.balance_mes - compra.monto

    # Promedio diario sobre los días transcurridos, no sobre los días con
    # gasto: si no gastó nada el martes, ese martes igual pasó.
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

    analisis.metas = _impacto_en_metas(compra, filas, dias_reales)
    return analisis


def _primer_dia(filas: list[dict], por_defecto: date) -> date:
    """La fecha del movimiento más viejo de la ventana.

    Si alguien empezó a usar el bot hace cinco días, su promedio diario se
    calcula sobre cinco días y no sobre sesenta: dividir por 60 diría que gasta
    una décima parte de lo que gasta.
    """
    fechas = []
    for f in filas:
        try:
            fechas.append(date.fromisoformat(f["fecha"]))
        except (KeyError, ValueError):
            continue
    return min(fechas) if fechas else por_defecto


def _impacto_en_metas(
    compra: CompraHipotetica, filas: list[dict], dias: int
) -> list[tuple[str, Decimal, Decimal | None, Decimal | None]]:
    """Cuánto se atrasaría cada meta si esa plata no se ahorra.

    El razonamiento: al ritmo al que viene ahorrando, ¿cuánto tarda en juntar
    el monto de la compra? Ese es el atraso. Es una estimación y así se dice
    en el texto: supone que el ritmo se mantiene, que nunca es del todo cierto.
    """
    try:
        objetivos = obtener_objetivos(solo_activos=True)
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
            continue  # una meta en dólares no se atrasa por un gasto en pesos
        try:
            meta = Decimal(str(objetivo["monto_objetivo"]))
            aportado = total_imputado(objetivo["id"], compra.moneda)
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

    return metas[:3]  # con más de tres, el mensaje se vuelve un informe


# --------------------------------------------------------------------------
# Redacción
# --------------------------------------------------------------------------


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

    # 1. El mes
    lineas.append(f"Este mes llevás gastados {fmt(analisis.gastado_mes, moneda)}.")
    if analisis.ingresos_mes > 0:
        signo = "" if analisis.balance_despues >= 0 else " (en rojo)"
        lineas.append(
            f"Tu balance va {fmt(analisis.balance_mes, moneda)} y quedaría en "
            f"{fmt(analisis.balance_despues, moneda)}{signo}."
        )
    else:
        # Sin ingresos cargados el balance no significa nada: decirlo es mejor
        # que mostrar un número negativo que solo refleja lo que falta cargar.
        lineas.append(
            "No tengo ingresos cargados este mes, así que no puedo calcular el balance."
        )

    # 2. Equivalencia en días
    if analisis.dias_equivalentes is not None:
        lineas.append("")
        lineas.append(
            f"Equivale a {_dias(analisis.dias_equivalentes)} de tu gasto promedio "
            f"({fmt(analisis.promedio_diario, moneda)} por día)."
        )

    # 3. El rubro
    if analisis.gastado_en_rubro is not None and analisis.gastado_en_rubro > 0:
        lineas.append(
            f"En {compra.categoria} ya llevás {fmt(analisis.gastado_en_rubro, moneda)} este mes."
        )

    # 4. Las metas
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

    # 5. El cierre: se devuelve la decisión, sin adjetivos.
    lineas.append("")
    lineas.append("Son los números. La decisión es tuya 🙂")
    lineas.append("Si al final lo comprás, decímelo y lo anoto.")

    return "\n".join(lineas)
