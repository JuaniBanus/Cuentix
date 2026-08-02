"""Persistencia en Supabase (Postgres), vía la API REST de PostgREST.

Reemplaza la implementación anterior con sqlite3 manteniendo exactamente las
mismas funciones y los mismos tipos de retorno, así el resto de la app no
cambia. La única diferencia de firma es que desapareció el parámetro
`db_path`, que ya no tiene sentido.

Dos cosas heredadas del diseño anterior que conviene conocer:

- Las sumas se siguen haciendo en Python con Decimal, no con agregaciones en
  SQL. A escala de finanzas personales el costo es irrelevante y evita
  depender de las funciones de agregación de PostgREST.
- La columna `monto` ahora es numeric(14,2) —un decimal de verdad, no TEXT
  como en SQLite—, pero PostgREST la serializa como número JSON, que Python
  parsea a float. Por eso toda lectura pasa por `_a_decimal`.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from postgrest import APIError
from supabase import Client, create_client

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.models import Moneda, Movimiento, TipoMovimiento

logger = logging.getLogger(__name__)

TABLA = "movimientos"

# PostgREST tiene un tope de filas por respuesta (1000 por defecto en
# Supabase). Sin paginar, un total sobre todo el historial se calcularía
# en silencio sobre las primeras 1000 filas nomás.
PAGINA = 1000

# La columna es numeric(14,2): todo monto se normaliza a dos decimales.
_CENTAVOS = Decimal("0.01")

_cliente: Client | None = None


class DBError(RuntimeError):
    """Falló una operación contra la base."""


def _obtener_cliente() -> Client:
    """Cliente Supabase compartido, creado perezosamente."""
    global _cliente
    if _cliente is None:
        _cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _cliente


def _a_decimal(valor: Any) -> Decimal:
    """Convierte a Decimal lo que PostgREST haya devuelto para un numeric.

    `Decimal(str(float))` recupera el valor exacto: str() da la repr más corta
    que round-trippea, y float64 garantiza 15 dígitos significativos contra
    los 14 de numeric(14,2).

    El quantize deja siempre dos decimales, como la columna: sin él, un
    8500.50 vuelve del JSON como 8500.5 y los totales quedan con una cantidad
    de decimales que varía según los datos.
    """
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return valor.quantize(_CENTAVOS)


def _aplicar_filtros(
    consulta: Any,
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
) -> Any:
    """Encadena sobre la query solo los filtros que vengan definidos."""
    if desde is not None:
        consulta = consulta.gte("fecha", desde.isoformat())
    if hasta is not None:
        consulta = consulta.lte("fecha", hasta.isoformat())
    if tipo is not None:
        consulta = consulta.eq("tipo", tipo.value)
    if moneda is not None:
        consulta = consulta.eq("moneda", moneda.value)
    if categoria is not None:
        # Las categorías se guardan ya normalizadas en minúsculas.
        consulta = consulta.eq("categoria", categoria.strip().lower())
    return consulta


def _seleccionar(
    columnas: str,
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
    ordenar_reciente: bool = False,
    limite: int | None = None,
) -> list[dict]:
    """Trae filas paginando hasta agotarlas (o hasta `limite`)."""
    cliente = _obtener_cliente()
    filas: list[dict] = []
    offset = 0

    while True:
        tamano = PAGINA if limite is None else min(PAGINA, limite - len(filas))
        if tamano <= 0:
            break

        consulta = _aplicar_filtros(
            cliente.table(TABLA).select(columnas),
            desde=desde,
            hasta=hasta,
            tipo=tipo,
            moneda=moneda,
            categoria=categoria,
        )
        if ordenar_reciente:
            consulta = consulta.order("fecha", desc=True).order("id", desc=True)
        consulta = consulta.range(offset, offset + tamano - 1)

        try:
            respuesta = consulta.execute()
        except APIError as exc:
            detalle = getattr(exc, "message", None) or str(exc)
            logger.error("Supabase rechazó la consulta: %s", detalle)
            raise DBError(f"Error consultando la base: {detalle}") from exc
        except Exception as exc:  # red caída, DNS, timeout
            logger.exception("Error de red contra Supabase")
            raise DBError("No pude comunicarme con la base de datos.") from exc

        lote = respuesta.data or []
        filas.extend(lote)
        if len(lote) < tamano:  # última página
            break
        offset += len(lote)

    return filas


def init_db() -> None:
    """Verifica que la tabla exista y sea accesible.

    La tabla se crea una sola vez desde el SQL Editor de Supabase, así que acá
    no hay DDL que ejecutar. Se mantiene el nombre y la llamada en el lifespan
    de FastAPI porque sirve para fallar al arrancar —y no en el primer
    mensaje— si la URL, la clave o la tabla están mal.
    """
    try:
        _obtener_cliente().table(TABLA).select("id").limit(1).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(
            f"No pude leer la tabla '{TABLA}' en Supabase: {detalle}. "
            "Revisá que exista y que SUPABASE_KEY sea la clave service_role."
        ) from exc
    except Exception as exc:
        raise DBError(f"No pude conectarme a Supabase ({SUPABASE_URL}).") from exc


def guardar_movimiento(movimiento: Movimiento) -> int:
    """Inserta un Movimiento y devuelve el id asignado.

    `created_at` lo pone Postgres solo (DEFAULT now()).
    """
    fila = {
        "fecha": movimiento.fecha.isoformat(),
        "tipo": movimiento.tipo.value,
        # str() y no float(): el JSON sale con el decimal exacto y Postgres
        # lo castea a numeric sin pasar por punto flotante.
        "monto": str(movimiento.monto),
        "moneda": movimiento.moneda.value,
        "categoria": movimiento.categoria,
        "descripcion": movimiento.descripcion,
    }

    try:
        respuesta = _obtener_cliente().table(TABLA).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el insert: %s", detalle)
        raise DBError(f"No pude guardar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert no devolvió la fila creada.")
    return int(respuesta.data[0]["id"])


class Total:
    """Total de una moneda: cuánta plata y cuántos movimientos la componen."""

    __slots__ = ("monto", "cantidad")

    def __init__(self, monto: Decimal = Decimal("0"), cantidad: int = 0) -> None:
        self.monto = monto
        self.cantidad = cantidad

    def sumar(self, monto: Decimal) -> None:
        self.monto += monto
        self.cantidad += 1

    def __repr__(self) -> str:
        return f"Total({self.monto}, {self.cantidad} mov.)"


def totales_por_moneda(
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
) -> dict[Moneda, Total]:
    """Suma los montos que cumplen los filtros, separados por moneda.

    Nunca mezcla ARS con USD: sumar monedas distintas daría un número sin
    ningún significado. Devuelve solo las monedas que tienen movimientos.
    """
    filas = _seleccionar(
        "moneda,monto",
        desde=desde,
        hasta=hasta,
        tipo=tipo,
        moneda=moneda,
        categoria=categoria,
    )

    totales: dict[Moneda, Total] = {}
    for fila in filas:
        clave = Moneda(fila["moneda"])
        totales.setdefault(clave, Total()).sumar(_a_decimal(fila["monto"]))
    return totales


def totales_por_categoria(
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
) -> list[tuple[str, Moneda, Total]]:
    """Desglosa los totales por categoría, de mayor a menor monto.

    Cada entrada es (categoria, moneda, Total). Una misma categoría aparece
    una vez por cada moneda en la que haya movimientos.
    """
    filas = _seleccionar(
        "categoria,moneda,monto", desde=desde, hasta=hasta, tipo=tipo, moneda=moneda
    )

    acumulado: dict[tuple[str, Moneda], Total] = {}
    for fila in filas:
        clave = (fila["categoria"], Moneda(fila["moneda"]))
        acumulado.setdefault(clave, Total()).sumar(_a_decimal(fila["monto"]))

    return sorted(
        ((cat, mon, total) for (cat, mon), total in acumulado.items()),
        key=lambda item: item[2].monto,
        reverse=True,
    )


def balance(
    *,
    desde: date | None = None,
    hasta: date | None = None,
    moneda: Moneda | None = None,
) -> dict[Moneda, dict[str, Decimal]]:
    """Ingresos menos gastos, por moneda.

    Ahorro e inversión quedan afuera del balance a propósito: esa plata sigue
    siendo tuya, solo cambió de lugar. Contarla como gasto daría un balance
    falsamente negativo.
    """
    ingresos = totales_por_moneda(
        desde=desde, hasta=hasta, tipo=TipoMovimiento.INGRESO, moneda=moneda
    )
    gastos = totales_por_moneda(
        desde=desde, hasta=hasta, tipo=TipoMovimiento.GASTO, moneda=moneda
    )

    resultado: dict[Moneda, dict[str, Decimal]] = {}
    for clave in sorted(set(ingresos) | set(gastos), key=lambda m: m.value):
        entrada = ingresos.get(clave, Total()).monto
        salida = gastos.get(clave, Total()).monto
        resultado[clave] = {
            "ingresos": entrada,
            "gastos": salida,
            "balance": entrada - salida,
        }
    return resultado


def obtener_movimientos(
    *,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
    limite: int = 100,
) -> list[dict]:
    """Consulta movimientos con filtros opcionales, del más reciente al más viejo.

    Devuelve dicts (no Movimiento) para conservar `id` y `created_at`, que no
    forman parte del modelo. La clave "movimiento" trae el objeto ya validado.
    """
    filas = _seleccionar(
        "*",
        desde=desde,
        hasta=hasta,
        tipo=tipo,
        moneda=moneda,
        categoria=categoria,
        ordenar_reciente=True,
        limite=limite,
    )

    resultados = []
    for fila in filas:
        registro = dict(fila)
        registro["movimiento"] = Movimiento(
            fecha=registro["fecha"],
            tipo=registro["tipo"],
            monto=_a_decimal(registro["monto"]),
            moneda=registro["moneda"],
            categoria=registro["categoria"],
            descripcion=registro["descripcion"],
        )
        resultados.append(registro)
    return resultados
