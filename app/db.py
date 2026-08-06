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
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from postgrest import APIError
from supabase import Client, create_client

from app.config import SUPABASE_KEY, SUPABASE_URL, SUPABASE_USER_ID
from app.models import Alerta, Inversion, Moneda, Movimiento, TipoMovimiento

logger = logging.getLogger(__name__)

TABLA = "movimientos"
TABLA_OBJETIVOS = "objetivos"
TABLA_INVERSIONES = "inversiones"
TABLA_ALERTAS = "alertas"

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


def guardar_movimiento(movimiento: Movimiento, objetivo_id: str | None = None) -> int:
    """Inserta un Movimiento y devuelve el id asignado.

    `created_at` lo pone Postgres solo (DEFAULT now()).

    `objetivo_id` se pasa cuando el ahorro ya se pudo imputar en el momento. Si
    hay que preguntar primero, el movimiento se guarda igual sin él y después
    se imputa con `imputar_movimiento`: la plata se apartó, y perder el
    registro por una duda sobre a qué objetivo va sería el peor negocio.
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
        # None viaja como null y la columna queda vacía, que es lo que
        # corresponde cuando el usuario no dijo dónde guardó la plata.
        "cuenta": movimiento.cuenta,
        "objetivo_id": objetivo_id,
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


# --------------------------------------------------------------------------
# Objetivos de ahorro
# --------------------------------------------------------------------------
#
# El bot escribe con la clave service_role, que saltea RLS. Eso trae dos cosas
# que hay que tener presentes:
#
# 1. Al leer ve los objetivos de TODOS los usuarios. Por eso se filtra por
#    SUPABASE_USER_ID cuando está configurado.
# 2. Al insertar, el `default auth.uid()` de la columna user_id devuelve null
#    —no hay sesión de nadie—, y la columna es NOT NULL. Así que el user_id hay
#    que mandarlo explícito, y sin SUPABASE_USER_ID no se pueden crear.


def obtener_objetivos(*, solo_activos: bool = True) -> list[dict]:
    """Los objetivos del usuario, para buscar a cuál imputar un ahorro."""
    cliente = _obtener_cliente()
    consulta = cliente.table(TABLA_OBJETIVOS).select("id, nombre, monto_objetivo, moneda, estado")

    if SUPABASE_USER_ID:
        consulta = consulta.eq("user_id", SUPABASE_USER_ID)
    if solo_activos:
        # Los completados y pausados no se ofrecen: sumarle a algo terminado
        # casi nunca es lo que se quiso decir.
        consulta = consulta.eq("estado", "activo")

    try:
        return consulta.execute().data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la consulta de objetivos: %s", detalle)
        raise DBError(f"Error consultando los objetivos: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando objetivos")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def crear_objetivo(*, nombre: str, monto_objetivo: Decimal, moneda: Moneda) -> dict:
    """Crea un objetivo y devuelve la fila.

    Raises:
        DBError: si no hay SUPABASE_USER_ID configurado. Sin él la fila no
            tendría dueño y Postgres la rechazaría por el NOT NULL.
    """
    if not SUPABASE_USER_ID:
        raise DBError(
            "No puedo crear objetivos: falta configurar SUPABASE_USER_ID. "
            "Se crean desde la web."
        )

    fila = {
        "user_id": SUPABASE_USER_ID,
        "nombre": nombre,
        "monto_objetivo": str(monto_objetivo),
        "moneda": moneda.value,
    }

    try:
        respuesta = _obtener_cliente().table(TABLA_OBJETIVOS).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el objetivo: %s", detalle)
        raise DBError(f"No pude crear el objetivo: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red creando el objetivo")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert del objetivo no devolvió la fila creada.")
    return respuesta.data[0]


def imputar_movimiento(movimiento_id: int, objetivo_id: str) -> None:
    """Le asigna un objetivo a un movimiento ya guardado."""
    try:
        _obtener_cliente().table(TABLA).update({"objetivo_id": objetivo_id}).eq(
            "id", movimiento_id
        ).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la imputación: %s", detalle)
        raise DBError(f"No pude imputar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red imputando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def total_imputado(objetivo_id: str, moneda: Moneda) -> Decimal:
    """Cuánto se lleva ahorrado para un objetivo, en su moneda.

    El filtro por moneda no es un detalle: un aporte de US$400 imputado a una
    meta en pesos sumaría 400 sobre 500.000.
    """
    filas = _seleccionar_imputados(objetivo_id, moneda)
    return sum((_a_decimal(f["monto"]) for f in filas), Decimal("0"))


def _seleccionar_imputados(objetivo_id: str, moneda: Moneda) -> list[dict]:
    cliente = _obtener_cliente()
    try:
        return (
            cliente.table(TABLA)
            .select("monto")
            .eq("objetivo_id", objetivo_id)
            .eq("moneda", moneda.value)
            .eq("tipo", TipoMovimiento.AHORRO.value)
            .execute()
            .data
            or []
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"Error consultando el progreso: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando el progreso")
        raise DBError("No pude comunicarme con la base de datos.") from exc


# --------------------------------------------------------------------------
# Inversiones
# --------------------------------------------------------------------------


def guardar_inversion(inversion: Inversion) -> str:
    """Inserta una tenencia en `inversiones` y devuelve su id (uuid).

    El `user_id` va explícito: el default auth.uid() de la tabla no se completa
    con service_role, que es como escribe el bot.
    """
    if not SUPABASE_USER_ID:
        raise DBError(
            "Falta SUPABASE_USER_ID en la configuración: sin ese dato no se "
            "puede saber de quién es la inversión."
        )

    fila = {
        "user_id": SUPABASE_USER_ID,
        "tipo": inversion.tipo.value,
        "ticker": inversion.ticker,
        "nombre": inversion.nombre,
        # str() y no float(): el JSON lleva el decimal exacto y Postgres lo
        # castea a numeric sin pasar por punto flotante.
        "cantidad": str(inversion.cantidad),
        "precio_compra": str(inversion.precio_compra),
        "moneda": inversion.moneda.value,
        "fecha_compra": inversion.fecha_compra.isoformat(),
        "sector": inversion.sector,
    }

    try:
        respuesta = _obtener_cliente().table(TABLA_INVERSIONES).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el insert de inversión: %s", detalle)
        raise DBError(f"No pude guardar la inversión: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando la inversión")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert de inversión no devolvió la fila creada.")
    return str(respuesta.data[0]["id"])


# --------------------------------------------------------------------------
# Alertas de precio
# --------------------------------------------------------------------------


def crear_alerta(
    alerta: Alerta,
    *,
    chat_id: int,
    referencia: Decimal | None,
    moneda: str | None,
) -> dict:
    """Guarda una alerta y devuelve la fila.

    `referencia` es el precio del momento: contra él se miden después los
    porcentajes. Se guarda al crear y no se recalcula, para que "baja 5%"
    signifique siempre 5% desde que la pediste.
    """
    if not SUPABASE_USER_ID:
        raise DBError(
            "Falta SUPABASE_USER_ID en la configuración: sin ese dato no se "
            "puede saber de quién es la alerta."
        )

    fila = {
        "user_id": SUPABASE_USER_ID,
        "chat_id": chat_id,
        "ticker": alerta.ticker,
        "mercado": alerta.mercado,
        "tipo": alerta.tipo.value,
        "umbral": str(alerta.umbral),
        "referencia": str(referencia) if referencia is not None else None,
        "moneda": moneda,
    }

    try:
        respuesta = _obtener_cliente().table(TABLA_ALERTAS).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la alerta: %s", detalle)
        raise DBError(f"No pude crear la alerta: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red creando la alerta")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert de la alerta no devolvió la fila creada.")
    return respuesta.data[0]


def alertas_activas() -> list[dict]:
    """Todas las alertas encendidas, de todos los usuarios.

    Sin filtrar por usuario a propósito: la corrida del cron no la pide nadie
    en particular, revisa las de todos. Por eso el endpoint que la dispara va
    protegido por un secreto y no por una sesión.
    """
    try:
        return (
            _obtener_cliente()
            .table(TABLA_ALERTAS)
            .select("*")
            .eq("activa", True)
            .execute()
            .data
            or []
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"Error consultando las alertas: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando alertas")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def alertas_de_chat(chat_id: int) -> list[dict]:
    """Las alertas activas de un chat, para poder listarlas por Telegram."""
    try:
        return (
            _obtener_cliente()
            .table(TABLA_ALERTAS)
            .select("*")
            .eq("chat_id", chat_id)
            .eq("activa", True)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"Error consultando las alertas: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando alertas del chat")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def apagar_alerta(alerta_id: str, *, precio: Decimal | None = None) -> None:
    """Marca una alerta como disparada.

    Se apaga en vez de dejarla sonar de nuevo: un papel que quedó debajo del
    umbral cumpliría la condición en cada corrida y mandaría un mensaje por
    hora hasta que alguien lo note.
    """
    cambios: dict[str, Any] = {
        "activa": False,
        "disparada_en": datetime.now(timezone.utc).isoformat(),
    }
    if precio is not None:
        cambios["precio_disparo"] = str(precio)

    try:
        _obtener_cliente().table(TABLA_ALERTAS).update(cambios).eq("id", alerta_id).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude apagar la alerta: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red apagando la alerta")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def borrar_alertas_de_chat(chat_id: int) -> int:
    """Apaga todas las de un chat. Devuelve cuántas."""
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_ALERTAS)
            .update({"activa": False})
            .eq("chat_id", chat_id)
            .eq("activa", True)
            .execute()
        )
        return len(respuesta.data or [])
    except Exception as exc:
        logger.exception("Error apagando las alertas del chat")
        raise DBError("No pude comunicarme con la base de datos.") from exc


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
            # .get() y no [...]: si todavía no se corrió el ALTER TABLE, la
            # columna no viene en la respuesta y leer movimientos viejos no
            # tiene por qué romperse.
            cuenta=registro.get("cuenta"),
        )
        resultados.append(registro)
    return resultados
