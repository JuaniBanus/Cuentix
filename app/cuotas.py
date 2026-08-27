"""«¿Cuotas o contado?»: cuál de las dos formas de pagar sale más barata."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.models import Financiacion
from app.tasas import Tasas

logger = logging.getLogger(__name__)

_PRECISION = Decimal("0.000001")
_TASA_MAXIMA = Decimal("10")


def valor_presente(cuota: Decimal, cuotas: int, tasa: Decimal) -> Decimal:
    """Cuánto valen HOY N cuotas iguales, descontadas a `tasa` mensual."""
    if tasa <= -1:
        return cuota * cuotas
    total = Decimal("0")
    factor = Decimal("1") + tasa
    for k in range(1, cuotas + 1):
        total += cuota / (factor ** k)
    return total


def tasa_implicita(cuota: Decimal, cuotas: int, contado: Decimal) -> Decimal | None:
    """La TEM que iguala el valor presente de las cuotas al precio contado."""
    if cuotas <= 0 or contado <= 0 or cuota <= 0:
        return None

    total = cuota * cuotas
    if total <= contado:
        return Decimal("0")

    bajo, alto = Decimal("0"), _TASA_MAXIMA
    if valor_presente(cuota, cuotas, alto) > contado:
        return None

    for _ in range(200):
        medio = (bajo + alto) / 2
        if valor_presente(cuota, cuotas, medio) > contado:
            bajo = medio
        else:
            alto = medio
        if alto - bajo < _PRECISION:
            break

    return ((bajo + alto) / 2).quantize(Decimal("0.00001"))


class Comparacion:
    """El resultado del análisis, listo para redactar."""

    __slots__ = (
        "financiacion", "total_cuotas", "recargo", "recargo_pct",
        "tem_implicita", "tem_referencia", "vpn_cuotas", "ahorro",
        "conviene_financiar", "tasas",
    )

    def __init__(self, financiacion: Financiacion, tasas: Tasas) -> None:
        self.financiacion = financiacion
        self.tasas = tasas

        cuota, n, contado = financiacion.monto_cuota, financiacion.cuotas, financiacion.precio_contado

        self.total_cuotas = (cuota * n).quantize(Decimal("0.01"))
        self.recargo = (self.total_cuotas - contado).quantize(Decimal("0.01"))
        self.recargo_pct = (
            (self.recargo / contado * 100).quantize(Decimal("0.1"))
            if contado > 0 else Decimal("0")
        )

        self.tem_referencia = financiacion.tasa_mensual or tasas.tem_inversion

        self.tem_implicita = tasa_implicita(cuota, n, contado)
        self.vpn_cuotas = valor_presente(cuota, n, self.tem_referencia).quantize(Decimal("0.01"))
        self.ahorro = (contado - self.vpn_cuotas).quantize(Decimal("0.01"))
        self.conviene_financiar = self.ahorro > 0


def comparar(financiacion: Financiacion, tasas: Tasas) -> Comparacion:
    return Comparacion(financiacion, tasas)


def veredicto_con(financiacion: Financiacion, tasa: Decimal) -> tuple[bool, Decimal]:
    """(conviene financiar, cuánto se ahorra) con una tasa alternativa."""
    vpn = valor_presente(financiacion.monto_cuota, financiacion.cuotas, tasa)
    ahorro = (financiacion.precio_contado - vpn).quantize(Decimal("0.01"))
    return ahorro > 0, ahorro


def _pct(valor: Decimal) -> str:
    return f"{valor * 100:.2f}".rstrip("0").rstrip(".") + "%"


def redactar(
    comparacion: Comparacion,
    formatear_monto,
    tiene_inversiones: bool = False,
    cartera=None,
) -> str:
    """El mensaje al usuario: la cuenta, la conclusión y el disclaimer."""
    f = comparacion.financiacion
    fmt = formatear_monto
    moneda = f.moneda
    lineas: list[str] = []

    que = f.que or "eso"
    lineas.append(f"💳 {que}: {f.cuotas} cuotas de {fmt(f.monto_cuota, moneda)} o {fmt(f.precio_contado, moneda)} al contado.")
    lineas.append("")

    if comparacion.recargo > 0:
        lineas.append(
            f"En pesos, las cuotas suman {fmt(comparacion.total_cuotas, moneda)}: "
            f"{fmt(comparacion.recargo, moneda)} más ({comparacion.recargo_pct}%)."
        )
    elif comparacion.recargo < 0:
        lineas.append(
            f"En pesos, las cuotas suman {fmt(comparacion.total_cuotas, moneda)}: "
            f"{fmt(abs(comparacion.recargo), moneda)} MENOS que el contado."
        )
    else:
        lineas.append("En pesos suman exactamente lo mismo: son cuotas sin interés.")

    lineas.append("")
    lineas.append("Pero un peso de dentro de un año no vale un peso de hoy 👇")
    lineas.append("")

    referencia = _pct(comparacion.tem_referencia)
    origen = (
        "la tasa que me pasaste"
        if f.tasa_mensual is not None
        else f"{comparacion.tasas.fuente_tasa}"
    )
    lineas.append(f"• Poniendo la plata a rendir: {referencia} por mes ({origen}).")

    if comparacion.tem_implicita is not None:
        lineas.append(f"• La financiación te cobra: {_pct(comparacion.tem_implicita)} por mes.")

    if comparacion.tasas.inflacion_mensual is not None:
        lineas.append(
            f"• De referencia, la inflación viene a {_pct(comparacion.tasas.inflacion_mensual)} mensual."
        )

    lineas.append("")
    lineas.append(
        f"Pagando en cuotas y dejando la plata rindiendo, hoy te alcanzaría con "
        f"{fmt(comparacion.vpn_cuotas, moneda)} para cubrirlas todas."
    )

    lineas.append("")
    if comparacion.conviene_financiar:
        lineas.append(
            f"👉 Conviene EN CUOTAS. Te ahorrás {fmt(comparacion.ahorro, moneda)} "
            "medido en plata de hoy."
        )
        if comparacion.tem_implicita is not None:
            lineas.append(
                f"El razonamiento: te financian al {_pct(comparacion.tem_implicita)} "
                f"y tu plata rinde {referencia}. Te prestan más barato de lo que ganás."
            )
    else:
        lineas.append(
            f"👉 Conviene AL CONTADO. Financiar te cuesta "
            f"{fmt(abs(comparacion.ahorro), moneda)} de más en plata de hoy."
        )
        if comparacion.tem_implicita is not None:
            lineas.append(
                f"El razonamiento: te financian al {_pct(comparacion.tem_implicita)} "
                f"y tu plata rinde {referencia}. El crédito sale más caro de lo que ganás."
            )

    if cartera is not None:
        lineas.append("")
        conviene_cartera, ahorro_cartera = veredicto_con(f, cartera.tem)
        lineas.append(
            f"📈 Tus inversiones en {cartera.moneda.value} vienen rindiendo "
            f"{_pct(cartera.tem)} por mes "
            f"({cartera.cotizadas} de {cartera.posiciones} posiciones, "
            f"{cartera.meses_promedio} meses promedio)."
        )
        if conviene_cartera == comparacion.conviene_financiar:
            lineas.append("Con esa tasa la conclusión no cambia.")
        else:
            cual = "EN CUOTAS" if conviene_cartera else "AL CONTADO"
            lineas.append(
                f"⚠️ Con esa tasa se da vuelta: convendría {cual} "
                f"({fmt(abs(ahorro_cartera), moneda)} de diferencia). "
                "Cuál vale depende de si esperás que tu cartera siga rindiendo igual."
            )

    lineas.append("")
    avisos = ["Es orientativo: supone que la tasa se mantiene los "
              f"{f.cuotas} meses y no cuenta comisiones ni seguros del comercio."]
    if comparacion.tasas.estimadas:
        avisos.append("No pude consultar las tasas de hoy, así que usé una estimación.")
    if cartera is not None:
        avisos.append(
            "El rendimiento de tu cartera es lo que YA pasó, no una promesa: "
            "sirve de referencia, no de pronóstico."
        )
    elif tiene_inversiones and f.tasa_mensual is None:
        avisos.append(
            "Tenés inversiones cargadas pero no pude calcular su rendimiento "
            "(muy nuevas o sin cotización). Si sabés a cuánto te rinden, "
            "decímelo («…si gano 4% por mes») y rehago la cuenta."
        )
    avisos.append("Y ojo: la cuota tenés que poder pagarla todos los meses.")
    lineas.append("ℹ️ " + " ".join(avisos))

    return "\n".join(lineas)


ETIQUETA_FALTANTE = {
    "cuotas": "en cuántas cuotas",
    "monto_cuota": "de cuánto es cada cuota",
    "precio_contado": "cuánto sale al contado",
}


def pedir_faltantes(faltantes: tuple[str, ...]) -> str:
    """Pide lo que falta para poder comparar, sin suponer nada."""
    pedidos = [ETIQUETA_FALTANTE.get(c, c) for c in faltantes]
    detalle = pedidos[0] if len(pedidos) == 1 else ", ".join(pedidos[:-1]) + f" y {pedidos[-1]}"
    return (
        f"Para comparar cuotas contra contado me falta saber {detalle}.\n\n"
        "Mandámelo completo, por ejemplo:\n"
        "«¿me conviene el celu en 12 cuotas de 100 mil o 900 mil al contado?»"
    )
