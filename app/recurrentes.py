"""Gastos recurrentes: qué se está pagando todos los meses sin mirarlo.

Espejo en Python de web/js/recurrentes.js. Se duplica por el mismo motivo que
el termómetro: la web lee Supabase directo y el bot no puede depender de que
la web esté abierta, ni al revés.

QUÉ CUENTA COMO RECURRENTE — tres condiciones, y las tres hacen falta:

  1. Al menos 3 cargos del mismo ítem. Con dos no hay periodicidad, hay una
     coincidencia.
  2. Espaciados regulares: la mediana de los días entre cargos tiene que
     parecerse a un período conocido, y ningún intervalo puede despegarse
     mucho de ella.
  3. Monto estable respecto de la mediana.

La tercera es la que separa un gasto RECURRENTE de uno FRECUENTE. El súper
también aparece todos los meses, pero por montos distintos: eso es un hábito,
no un débito automático.

LO QUE EL BOT HACE Y LO QUE NO
Sugiere revisar. No cancela nada, no puede cancelar nada, y no dice que haya
que cancelar: no sabe si el gimnasio al que no vas es un olvido o una decisión.
Muestra hace cuánto se paga y cuánto se lleva acumulado, que es el dato que
nadie tiene a mano, y ahí se detiene.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

CARGOS_MINIMOS = 3
TOLERANCIA_DIAS = Decimal("0.35")
TOLERANCIA_MONTO = Decimal("0.25")

# (nombre, días, cuántas veces por mes)
PERIODOS = (
    ("semanal", Decimal("7"), Decimal("4.33")),
    ("quincenal", Decimal("15"), Decimal("2")),
    ("mensual", Decimal("30.44"), Decimal("1")),
    ("bimestral", Decimal("61"), Decimal("0.5")),
    ("trimestral", Decimal("91"), Decimal("0.33")),
    ("anual", Decimal("365"), Decimal("1") / 12),
)


class Recurrente:
    """Un cargo que se repite con monto y período estables."""

    __slots__ = (
        "clave", "categoria", "cargos", "periodo", "monto_tipico", "por_mes",
        "primero", "ultimo", "dias_desde_ultimo", "total_pagado", "meses_activo",
    )

    def __init__(self, **kw) -> None:
        for campo in self.__slots__:
            setattr(self, campo, kw.get(campo))


def _mediana(valores: list[Decimal]) -> Decimal:
    if not valores:
        return Decimal("0")
    ordenados = sorted(valores)
    medio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[medio]
    return (ordenados[medio - 1] + ordenados[medio]) / 2


def _periodo_de(dias: Decimal) -> tuple[str, Decimal, Decimal] | None:
    """El período conocido más parecido, o None si no se parece a ninguno."""
    mejor, distancia = None, Decimal("999")
    for nombre, largo, por_mes in PERIODOS:
        d = abs(dias - largo) / largo
        if d < distancia:
            mejor, distancia = (nombre, largo, por_mes), d
    return mejor if distancia <= TOLERANCIA_DIAS else None


def _clave_de(fila: dict) -> str:
    """La del termómetro si está; si no, lo que haya."""
    for campo in ("clave_item", "comercio", "descripcion", "categoria"):
        valor = (fila.get(campo) or "").strip().lower()
        if valor:
            return valor
    return ""


def detectar(filas: list[dict], moneda: str, hoy: date | None = None) -> list[Recurrente]:
    """Los cargos recurrentes de una moneda, del que más pesa al que menos."""
    hoy = hoy or date.today()

    por_item: dict[str, list[tuple[date, Decimal, str]]] = {}
    for fila in filas:
        if fila.get("tipo") != "gasto" or fila.get("moneda") != moneda:
            continue
        clave = _clave_de(fila)
        if not clave:
            continue
        try:
            cuando = date.fromisoformat(fila["fecha"])
            monto = Decimal(str(fila["monto"]))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue
        if monto <= 0:
            continue
        por_item.setdefault(clave, []).append((cuando, monto, fila.get("categoria") or ""))

    salida: list[Recurrente] = []

    for clave, cargos in por_item.items():
        if len(cargos) < CARGOS_MINIMOS:
            continue
        cargos.sort(key=lambda c: c[0])

        intervalos = [
            Decimal((cargos[i][0] - cargos[i - 1][0]).days)
            for i in range(1, len(cargos))
            if (cargos[i][0] - cargos[i - 1][0]).days > 0
        ]
        if len(intervalos) < CARGOS_MINIMOS - 1:
            continue

        dias_mediana = _mediana(intervalos)
        if dias_mediana <= 0:
            continue
        if any(abs(d - dias_mediana) / dias_mediana > TOLERANCIA_DIAS for d in intervalos):
            continue

        periodo = _periodo_de(dias_mediana)
        if periodo is None:
            continue
        nombre, largo, por_mes = periodo

        montos = [c[1] for c in cargos]
        tipico = _mediana(montos)
        if tipico <= 0:
            continue
        if any(abs(m - tipico) / tipico > TOLERANCIA_MONTO for m in montos):
            continue

        dias_desde = (hoy - cargos[-1][0]).days

        salida.append(
            Recurrente(
                clave=clave,
                categoria=cargos[-1][2],
                cargos=len(cargos),
                periodo=nombre,
                monto_tipico=tipico.quantize(Decimal("0.01")),
                por_mes=(tipico * por_mes).quantize(Decimal("0.01")),
                primero=cargos[0][0],
                ultimo=cargos[-1][0],
                dias_desde_ultimo=dias_desde,
                total_pagado=sum(montos, Decimal("0")),
                meses_activo=round((cargos[-1][0] - cargos[0][0]).days / 30.44),
            )
        )

    salida.sort(key=lambda r: r.por_mes, reverse=True)
    return salida


def total_mensual(recurrentes: list[Recurrente]) -> Decimal:
    return sum((r.por_mes for r in recurrentes), Decimal("0"))


def redactar(recurrentes: list[Recurrente], moneda, formatear_monto) -> str:
    """El mensaje del bot. Informa y sugiere revisar; no aconseja cancelar."""
    if not recurrentes:
        return (
            "Todavía no detecté gastos recurrentes 🔍\n\n"
            "Necesito al menos 3 cargos del mismo ítem, espaciados parejo y por "
            "montos parecidos. Con más meses cargados esto mejora bastante."
        )

    total = total_mensual(recurrentes)
    lineas = [
        f"🔁 Tenés {len(recurrentes)} "
        f"{'gasto recurrente' if len(recurrentes) == 1 else 'gastos recurrentes'}, "
        f"{formatear_monto(total, moneda)} por mes en total:",
        "",
    ]

    for r in recurrentes[:8]:
        lineas.append(
            f"• {r.clave}: {formatear_monto(r.monto_tipico, moneda)} {r.periodo} "
            f"({r.cargos} cargos)"
        )

    if len(recurrentes) > 8:
        lineas.append(f"…y {len(recurrentes) - 8} más.")

    # La sugerencia: los que llevan mucho tiempo cobrándose. Se los nombra y se
    # invita a mirarlos, sin decir qué hacer.
    veteranos = [r for r in recurrentes if r.meses_activo >= 6]
    if veteranos:
        lineas.append("")
        lineas.append("Estos vienen de hace rato, por si querés revisarlos:")
        for r in veteranos[:3]:
            lineas.append(
                f"  {r.clave} — {r.meses_activo} meses, "
                f"{formatear_monto(r.total_pagado, moneda)} acumulados"
            )
        lineas.append("Los dejo a la vista nomás: si los usás, están bien donde están.")

    lineas.append("")
    lineas.append(
        "ℹ️ Esto mejora con el tiempo: cuantos más meses tengas cargados, "
        "mejor distingo una suscripción de una coincidencia."
    )
    return "\n".join(lineas)
