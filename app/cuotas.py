"""«¿Cuotas o contado?»: cuál de las dos formas de pagar sale más barata.

EL MÉTODO, Y POR QUÉ NO ES COMPARAR TOTALES

Lo intuitivo es sumar las cuotas y comparar contra el precio de contado: si
12 × $100.000 = $1.200.000 y al contado sale $900.000, "financiar sale
$300.000 más caro". Está mal, y en Argentina está muy mal.

Un peso dentro de doce meses no vale un peso de hoy. La plata que NO gastás
hoy queda rindiendo, y con esos intereses pagás parte de las cuotas. Lo que
hay que comparar es el VALOR PRESENTE de las cuotas contra el precio contado:

    VPN = Σ cuota / (1 + r)^k     con k = 1..N

donde r es la tasa mensual a la que podés poner la plata que no gastaste.

De ahí sale la comparación limpia: la TEM IMPLÍCITA de la financiación, que es
la tasa que hace que el valor presente de las cuotas iguale al precio contado.
Si esa tasa es MENOR que la que conseguís invirtiendo, financiar conviene:
te están prestando más barato de lo que a vos te rinde. Si es mayor, contado.

QUÉ TASA SE USA COMO REFERENCIA
La del plazo fijo, no la inflación. Para elegir entre dos formas de pagar lo
mismo, lo que decide es cuánto rinde la plata que no gastás. La inflación se
muestra al costado como contexto, porque es la que empuja las tasas, pero no
entra en la cuenta.

LO QUE ESTO NO ES
No es asesoramiento financiero. Supone que la tasa se mantiene constante los
N meses —que no pasa—, ignora comisiones y seguros que el comercio puede
sumar, y no sabe si podés sostener la cuota todos los meses. El mensaje lo
dice al final, sin letra chica.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.models import Financiacion
from app.tasas import Tasas

logger = logging.getLogger(__name__)

# Precisión y techo de la búsqueda de la tasa implícita.
_PRECISION = Decimal("0.000001")
_TASA_MAXIMA = Decimal("10")  # 1000% mensual: más que eso no es un caso real


def valor_presente(cuota: Decimal, cuotas: int, tasa: Decimal) -> Decimal:
    """Cuánto valen HOY N cuotas iguales, descontadas a `tasa` mensual.

    La primera cuota se cuenta a un mes, no hoy: es lo habitual con tarjeta,
    donde cae en el resumen siguiente. Si cayera hoy, el cálculo favorecería
    menos a la financiación.
    """
    if tasa <= -1:
        return cuota * cuotas
    total = Decimal("0")
    factor = Decimal("1") + tasa
    for k in range(1, cuotas + 1):
        total += cuota / (factor ** k)
    return total


def tasa_implicita(cuota: Decimal, cuotas: int, contado: Decimal) -> Decimal | None:
    """La TEM que iguala el valor presente de las cuotas al precio contado.

    Se resuelve por bisección y no con una fórmula porque no existe una
    cerrada para N cuotas. El valor presente baja cuando la tasa sube, así que
    la función es monótona y la bisección siempre converge.

    Devuelve None si no hay solución en un rango razonable (por ejemplo, si
    las cuotas suman menos que el contado: ahí no hay interés que valga).
    """
    if cuotas <= 0 or contado <= 0 or cuota <= 0:
        return None

    total = cuota * cuotas
    if total <= contado:
        # Financiar sale igual o menos en pesos nominales: la tasa implícita
        # es cero o negativa. Cero es la respuesta útil ("sin interés").
        return Decimal("0")

    bajo, alto = Decimal("0"), _TASA_MAXIMA
    if valor_presente(cuota, cuotas, alto) > contado:
        return None  # ni al 1000% mensual se descuenta tanto

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

        # La tasa de referencia: la que dijo el usuario gana sobre la del
        # mercado, porque él sabe dónde pone la plata y nosotros no.
        self.tem_referencia = financiacion.tasa_mensual or tasas.tem_inversion

        self.tem_implicita = tasa_implicita(cuota, n, contado)
        self.vpn_cuotas = valor_presente(cuota, n, self.tem_referencia).quantize(Decimal("0.01"))
        # Positivo = financiar deja plata en el bolsillo, medido en pesos de hoy.
        self.ahorro = (contado - self.vpn_cuotas).quantize(Decimal("0.01"))
        self.conviene_financiar = self.ahorro > 0


def comparar(financiacion: Financiacion, tasas: Tasas) -> Comparacion:
    return Comparacion(financiacion, tasas)


def veredicto_con(financiacion: Financiacion, tasa: Decimal) -> tuple[bool, Decimal]:
    """(conviene financiar, cuánto se ahorra) con una tasa alternativa.

    Sirve para mostrar el resultado bajo dos supuestos distintos en vez de
    elegir uno y esconder el otro: cuál conviene depende de a cuánto rinde la
    plata, y el usuario tiene derecho a ver esa bisagra.
    """
    vpn = valor_presente(financiacion.monto_cuota, financiacion.cuotas, tasa)
    ahorro = (financiacion.precio_contado - vpn).quantize(Decimal("0.01"))
    return ahorro > 0, ahorro


# --------------------------------------------------------------------------
# Redacción
# --------------------------------------------------------------------------


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

    # 1. Lo nominal, que es lo que todos miran primero.
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

    # 2. Por qué eso no alcanza.
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

    # 3. La cuenta que decide.
    lineas.append("")
    lineas.append(
        f"Pagando en cuotas y dejando la plata rindiendo, hoy te alcanzaría con "
        f"{fmt(comparacion.vpn_cuotas, moneda)} para cubrirlas todas."
    )

    # 4. La conclusión, con el razonamiento a la vista.
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

    # 4 bis. El mismo cálculo con lo que rinde SU cartera.
    #
    # Va como segundo escenario y no reemplazando al primero: es rendimiento
    # pasado, y en una cartera chica puede ser cualquier cosa. Mostrar los dos
    # deja a la vista de qué depende la conclusión, en vez de esconderlo.
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

    # 5. Lo que la cuenta no sabe.
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
