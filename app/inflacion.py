"""Inflación personal: cuánto subió la canasta propia del usuario.

CÓMO SE ARMA, Y POR QUÉ ASÍ

Por ítem: se compara la primera observación contra la última y se saca la tasa
mensual equivalente de forma GEOMÉTRICA. Un 20% en cuatro meses no es 5% por
mes, es 4,66%; dividir infla el número y el error crece con el plazo.

El índice general es el promedio de esas tasas PONDERADO POR LO QUE PESA CADA
ÍTEM EN EL GASTO del período base. Es como se arma un IPC de verdad: que el
alquiler suba 10% no es lo mismo que suba 10% el café, aunque ambos sean "un
ítem que aumentó 10%". Un promedio simple los trataría igual.

QUÉ ENTRA Y QUÉ NO
Solo los ítems comparables (ver app/items.py): servicios, donde el total es el
precio, y compras con precio unitario capturado. Las compras variables —súper,
comida— quedan afuera del índice y se informan aparte como GASTO, porque su
total mezcla precio con cantidad y no hay forma de separarlos.

Un ítem necesita al menos dos observaciones en MESES distintos. Dos compras
del mismo día no dicen nada sobre la evolución de un precio.

LO QUE ESTE NÚMERO NO ES
No es el IPC. Es la canasta de una sola persona, con los ítems que cargó, en
las fechas que cargó. Con pocos ítems es muy sensible: un alquiler que ajusta
una vez al año puede dominar el índice del mes en que ajusta. Por eso siempre
viaja con cuántos ítems lo sostienen.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from app.items import ClaseItem, clase_de

logger = logging.getLogger(__name__)

# Menos que esto y comparar dos precios es leer ruido.
MESES_MINIMOS = Decimal("0.8")
# Variaciones más extremas que esto casi siempre son otro ítem mal agrupado, o
# una carga distinta del mismo. Se excluyen del índice y se avisa.
VARIACION_ABSURDA = Decimal("10")  # +900% o -90%


class Observacion:
    """Un precio de un ítem en una fecha."""

    __slots__ = ("fecha", "precio", "es_unitario", "monto_gastado")

    def __init__(self, fecha: date, precio: Decimal, es_unitario: bool, monto_gastado: Decimal):
        self.fecha = fecha
        self.precio = precio
        self.es_unitario = es_unitario
        self.monto_gastado = monto_gastado


class ItemMedido:
    """Un ítem con su variación entre la primera y la última compra."""

    __slots__ = (
        "clave", "clase", "primera", "ultima", "precio_inicial", "precio_final",
        "variacion", "tem", "observaciones", "peso", "unitario",
    )

    def __init__(self, clave: str, clase: ClaseItem, obs: list[Observacion]) -> None:
        self.clave = clave
        self.clase = clase
        self.observaciones = len(obs)

        primera, ultima = obs[0], obs[-1]
        self.primera, self.ultima = primera.fecha, ultima.fecha
        self.precio_inicial, self.precio_final = primera.precio, ultima.precio
        self.unitario = primera.es_unitario

        # Cuánto pesa el ítem: lo que se gastó en él en todo el período. Es el
        # ponderador del índice.
        self.peso = sum((o.monto_gastado for o in obs), Decimal("0"))

        self.variacion = (
            (self.precio_final / self.precio_inicial - 1)
            if self.precio_inicial > 0 else Decimal("0")
        )

        meses = Decimal((self.ultima - self.primera).days) / Decimal("30.44")
        if meses >= MESES_MINIMOS and self.precio_inicial > 0:
            try:
                factor = float(self.precio_final / self.precio_inicial)
                self.tem = Decimal(str(factor ** (1 / float(meses)) - 1)).quantize(
                    Decimal("0.00001")
                )
            except (OverflowError, ValueError, ZeroDivisionError):
                self.tem = None
        else:
            self.tem = None


class Termometro:
    """El resultado completo: el índice y el detalle que lo sostiene."""

    __slots__ = ("tem", "items", "descartados", "desde", "hasta")

    def __init__(self) -> None:
        self.tem: Decimal | None = None
        self.items: list[ItemMedido] = []
        # Ítems que se repiten pero no se pueden medir, con el motivo.
        self.descartados: list[tuple[str, str]] = []
        self.desde: date | None = None
        self.hasta: date | None = None


def _precio_de(fila: dict) -> tuple[Decimal, bool] | None:
    """(precio, es_unitario). El unitario manda cuando está."""
    try:
        unitario = fila.get("precio_unitario")
        if unitario is not None:
            valor = Decimal(str(unitario))
            if valor > 0:
                return valor, True
        monto = Decimal(str(fila["monto"]))
        return (monto, False) if monto > 0 else None
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return None


def calcular(filas: list[dict]) -> Termometro:
    """Arma el termómetro a partir de movimientos ya filtrados a gastos.

    Espera filas con: fecha, monto, categoria, clave_item y, opcionalmente,
    precio_unitario. Las que no tengan clave_item se ignoran.
    """
    termometro = Termometro()

    por_item: dict[str, list[Observacion]] = {}
    categoria_de: dict[str, str] = {}
    unitario_de: dict[str, bool] = {}

    for fila in filas:
        clave = (fila.get("clave_item") or "").strip()
        if not clave:
            continue

        precio = _precio_de(fila)
        if precio is None:
            continue

        try:
            cuando = date.fromisoformat(fila["fecha"])
            gastado = Decimal(str(fila["monto"]))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue

        por_item.setdefault(clave, []).append(
            Observacion(cuando, precio[0], precio[1], gastado)
        )
        categoria_de.setdefault(clave, fila.get("categoria") or "")
        unitario_de[clave] = unitario_de.get(clave, False) or precio[1]

    medidos: list[ItemMedido] = []

    for clave, obs in por_item.items():
        obs.sort(key=lambda o: o.fecha)

        if len(obs) < 2:
            continue

        meses_distintos = {(o.fecha.year, o.fecha.month) for o in obs}
        if len(meses_distintos) < 2:
            termometro.descartados.append((clave, "todas las compras en el mismo mes"))
            continue

        clase = clase_de(categoria_de.get(clave, ""), unitario_de.get(clave, False))
        if clase is ClaseItem.VARIABLE:
            termometro.descartados.append(
                (clave, "el total mezcla precio y cantidad; falta el precio por unidad")
            )
            continue

        item = ItemMedido(clave, clase, obs)
        if item.tem is None:
            termometro.descartados.append((clave, "muy poco tiempo entre compras"))
            continue
        if abs(item.variacion) > VARIACION_ABSURDA:
            termometro.descartados.append(
                (clave, f"variación de {item.variacion * 100:.0f}%: parece otro ítem mezclado")
            )
            continue

        medidos.append(item)

    medidos.sort(key=lambda i: i.variacion, reverse=True)
    termometro.items = medidos

    if medidos:
        peso_total = sum((i.peso for i in medidos), Decimal("0"))
        if peso_total > 0:
            termometro.tem = (
                sum((i.tem * i.peso for i in medidos), Decimal("0")) / peso_total
            ).quantize(Decimal("0.00001"))
        termometro.desde = min(i.primera for i in medidos)
        termometro.hasta = max(i.ultima for i in medidos)

    return termometro


# --------------------------------------------------------------------------
# Detección de saltos, para el aviso del bot
# --------------------------------------------------------------------------

# Mínimo de compras previas para poder hablar de "lo que venía saliendo".
OBSERVACIONES_MINIMAS = 3
# Salto a partir del cual vale la pena decir algo.
SALTO_MINIMO = Decimal("0.15")


def detectar_salto(precio_nuevo: Decimal, previos: list[Decimal]) -> Decimal | None:
    """Cuánto se despegó el precio nuevo de lo habitual, o None.

    Se compara contra la MEDIANA de los precios previos y no contra el último:
    un mes raro no puede convertir al siguiente en una falsa alarma, ni tapar
    un aumento real.
    """
    if len(previos) < OBSERVACIONES_MINIMAS:
        return None

    ordenados = sorted(previos)
    medio = len(ordenados) // 2
    mediana = (
        ordenados[medio]
        if len(ordenados) % 2
        else (ordenados[medio - 1] + ordenados[medio]) / 2
    )
    if mediana <= 0:
        return None

    variacion = precio_nuevo / mediana - 1
    return variacion.quantize(Decimal("0.001")) if abs(variacion) >= SALTO_MINIMO else None
