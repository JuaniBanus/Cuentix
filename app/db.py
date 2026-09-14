"""Persistencia en Supabase (Postgres), vía la API REST de PostgREST."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from postgrest import APIError
from supabase import Client, create_client

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.models import (
    Alerta,
    Inversion,
    MedioPago,
    Moneda,
    Movimiento,
    TipoMovimiento,
)

logger = logging.getLogger(__name__)

TABLA = "movimientos"
TABLA_OBJETIVOS = "objetivos"
TABLA_INVERSIONES = "inversiones"
TABLA_ALERTAS = "alertas"
TABLA_RECORDATORIOS = "recordatorios"
TABLA_RETOS = "retos"
TABLA_RENDIMIENTOS = "rendimientos_billeteras"
TABLA_VINCULOS = "usuarios_telegram"
TABLA_PERFILES = "perfiles"
TABLA_CATEGORIAS = "categorias"
TABLA_MENSAJES = "mensajes_movimiento"

PAGINA = 1000

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
    """Convierte a Decimal lo que PostgREST haya devuelto para un numeric."""
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return valor.quantize(_CENTAVOS)


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _exigir(user_id: str) -> str:
    """Devuelve el user_id, o rompe si vino vacío."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise DBError(
            "Falta el user_id: no se puede leer ni escribir sin saber de quién "
            "son los datos."
        )
    return user_id.strip()


def vinculo_de_chat(chat_id: int) -> dict | None:
    """La fila de `usuarios_telegram` de ese chat, o None si no está vinculado."""
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA_VINCULOS)
            .select("chat_id, user_id, alias")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        ).data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la consulta del vínculo: %s", detalle)
        raise DBError(f"No pude leer el vínculo del chat: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando el vínculo del chat")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return filas[0] if filas else None


def pausar_cuenta(user_id: str, motivo: str = "") -> None:
    """Pone el perfil en 'pausado'. Va por la clave de servicio, no por el RPC
    de superusuario: acá no hay una persona logueada que lo autorice."""
    user_id = _exigir(user_id)
    try:
        (
            _obtener_cliente()
            .table(TABLA_PERFILES)
            .update({"estado": "pausado"})
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude pausar la cuenta: {detalle}") from exc
    logger.warning("Cuenta %s pausada automáticamente. %s", user_id, motivo)


def perfil_de(user_id: str) -> dict | None:
    """El perfil de un usuario, con su estado de cuenta. None si no existe."""
    user_id = _exigir(user_id)
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA_PERFILES)
            .select("user_id, email, estado, rol")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        ).data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la consulta del perfil: %s", detalle)
        raise DBError(f"No pude leer el perfil: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando el perfil")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return filas[0] if filas else None


def _aplicar_filtros(
    consulta: Any,
    *,
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
    medio_pago: MedioPago | None = None,
) -> Any:
    """Encadena sobre la query solo los filtros que vengan definidos."""
    consulta = consulta.eq("user_id", _exigir(user_id))

    if desde is not None:
        consulta = consulta.gte("fecha", desde.isoformat())
    if hasta is not None:
        consulta = consulta.lte("fecha", hasta.isoformat())
    if tipo is not None:
        consulta = consulta.eq("tipo", tipo.value)
    if moneda is not None:
        consulta = consulta.eq("moneda", moneda.value)
    if categoria is not None:
        consulta = consulta.eq("categoria", categoria.strip().lower())
    if medio_pago is not None:
        consulta = consulta.eq("medio_pago", medio_pago.value)
    return consulta


def _seleccionar(
    columnas: str,
    *,
    user_id: str,
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
            user_id=user_id,
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
        except Exception as exc:
            logger.exception("Error de red contra Supabase")
            raise DBError("No pude comunicarme con la base de datos.") from exc

        lote = respuesta.data or []
        filas.extend(lote)
        if len(lote) < tamano:
            break
        offset += len(lote)

    return filas


def init_db() -> None:
    """Verifica que la tabla exista y sea accesible."""
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

    for tabla in (TABLA_VINCULOS, TABLA_PERFILES):
        try:
            _obtener_cliente().table(tabla).select("user_id").limit(1).execute()
        except APIError as exc:
            detalle = getattr(exc, "message", None) or str(exc)
            raise DBError(
                f"No pude leer la tabla '{tabla}' en Supabase: {detalle}. "
                "Falta correr migrations/009_multiusuario.sql en el SQL Editor."
            ) from exc
        except Exception as exc:
            raise DBError(f"No pude conectarme a Supabase ({SUPABASE_URL}).") from exc


# La columna medio_pago llega con migrations/022_medio_pago.sql. Entre que
# Render despliega este código (se despliega solo apenas hay push) y que
# alguien corre el SQL hay una ventana en la que la columna NO existe, y en esa
# ventana el bot tiene que seguir registrando igual: quedarse sin poder anotar
# un gasto es mucho peor que anotarlo sin el medio de pago.
#
# Se detecta al primer rechazo y se recuerda, para no pagar un reintento por
# movimiento. Es el mismo criterio que con las categorías (019) y la tabla de
# mensajes (021): la migración pendiente degrada la función, no rompe el bot.
_hay_medio_pago = True

_COLUMNAS_ANALISIS = "fecha,tipo,monto,moneda,categoria,descripcion,cuenta"


def _sin_columna_medio_pago(exc: APIError) -> bool:
    """Si PostgREST rechazó porque la columna todavía no existe."""
    codigo = str(getattr(exc, "code", "") or "")
    detalle = (getattr(exc, "message", None) or str(exc)).lower()
    return "medio_pago" in detalle and codigo in {"42703", "PGRST204"}


def _olvidar_medio_pago() -> None:
    """Deja de mandar la columna en lo que queda de vida del proceso."""
    global _hay_medio_pago
    if _hay_medio_pago:
        logger.warning(
            "La columna medio_pago no existe todavía: sigo sin ella. "
            "¿Falta correr migrations/022_medio_pago.sql?"
        )
    _hay_medio_pago = False


def _columnas_analisis() -> str:
    """Las columnas que se piden para analizar, según exista o no medio_pago."""
    if _hay_medio_pago:
        return f"{_COLUMNAS_ANALISIS},medio_pago"
    return _COLUMNAS_ANALISIS


def _insertar(filas: list[dict]) -> list[dict]:
    """Inserta en movimientos, reintentando sin medio_pago si no existe."""
    if not _hay_medio_pago:
        filas = [{k: v for k, v in f.items() if k != "medio_pago"} for f in filas]

    try:
        return _obtener_cliente().table(TABLA).insert(filas).execute().data or []
    except APIError as exc:
        if not _sin_columna_medio_pago(exc):
            detalle = getattr(exc, "message", None) or str(exc)
            logger.error("Supabase rechazó el insert: %s", detalle)
            raise DBError(f"No pude guardar el movimiento: {detalle}") from exc
        _olvidar_medio_pago()
    except Exception as exc:
        logger.exception("Error de red guardando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    limpias = [{k: v for k, v in f.items() if k != "medio_pago"} for f in filas]
    try:
        return _obtener_cliente().table(TABLA).insert(limpias).execute().data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el insert: %s", detalle)
        raise DBError(f"No pude guardar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def guardar_movimiento(
    movimiento: Movimiento, objetivo_id: str | None = None, *, user_id: str
) -> int:
    """Inserta un Movimiento y devuelve el id asignado."""
    fila = {
        "user_id": _exigir(user_id),
        "fecha": movimiento.fecha.isoformat(),
        "tipo": movimiento.tipo.value,
        "monto": str(movimiento.monto),
        "moneda": movimiento.moneda.value,
        "categoria": movimiento.categoria,
        "descripcion": movimiento.descripcion,
        "comercio": movimiento.comercio,
        "clave_item": movimiento.clave_item,
        "cantidad": str(movimiento.cantidad) if movimiento.cantidad is not None else None,
        "unidad": movimiento.unidad,
        "precio_unitario": (
            str(movimiento.precio_unitario)
            if movimiento.precio_unitario is not None
            else None
        ),
        "cuenta": movimiento.cuenta,
        "medio_pago": movimiento.medio_pago.value if movimiento.medio_pago else None,
        "objetivo_id": objetivo_id,
    }

    creadas = _insertar([fila])
    if not creadas:
        raise DBError("El insert no devolvió la fila creada.")
    return int(creadas[0]["id"])


def obtener_categorias(*, user_id: str) -> list[dict]:
    """Las categorías que ese usuario puede usar: las base más las suyas.

    Las base son las filas con user_id nulo (019_categorias.sql). Van en la
    misma consulta que las propias porque el bot las necesita juntas en cada
    mensaje, para armar la lista que ve Gemini.
    """
    user_id = _exigir(user_id)
    if not _UUID.match(user_id):
        # El filtro `or` de PostgREST se arma como texto, así que el user_id se
        # interpola. Viene de la tabla de vínculos y nunca del usuario, pero un
        # valor raro acá sería un filtro roto: mejor cortar antes.
        raise DBError(f"El user_id no tiene forma de uuid: {user_id!r}")

    try:
        filas = (
            _obtener_cliente()
            .table(TABLA_CATEGORIAS)
            .select("id, user_id, nombre, tipo, emoji")
            .or_(f"user_id.is.null,user_id.eq.{user_id}")
            .execute()
        ).data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la consulta de categorías: %s", detalle)
        raise DBError(f"No pude leer las categorías: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando categorías")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return filas


def crear_categoria(*, user_id: str, nombre: str, tipo: TipoMovimiento) -> dict:
    """Crea una categoría propia y devuelve la fila.

    El user_id va siempre: una fila con user_id nulo sería una categoría BASE,
    visible para todos los usuarios del sistema.
    """
    fila = {
        "user_id": _exigir(user_id),
        "nombre": nombre,
        "tipo": tipo.value,
    }

    try:
        respuesta = _obtener_cliente().table(TABLA_CATEGORIAS).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la categoría: %s", detalle)
        raise DBError(f"No pude crear la categoría: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red creando la categoría")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert de la categoría no devolvió la fila creada.")
    return respuesta.data[0]


def borrar_categoria(*, user_id: str, nombre: str, tipo: TipoMovimiento) -> int:
    """Borra una categoría propia. Devuelve cuántas filas se llevó (0 o 1).

    El filtro por user_id no es decorativo: sin él esto borraría la categoría
    base de todos los usuarios.
    """
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_CATEGORIAS)
            .delete()
            .eq("user_id", _exigir(user_id))
            .eq("tipo", tipo.value)
            .eq("nombre", nombre)
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el borrado de la categoría: %s", detalle)
        raise DBError(f"No pude borrar la categoría: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red borrando la categoría")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return len(respuesta.data or [])


def uso_de_categoria(
    *, user_id: str, categoria: str, tipo: TipoMovimiento
) -> tuple[int, dict[Moneda, Decimal]]:
    """Cuántos movimientos usan esa etiqueta y por cuánto, para avisar al borrar."""
    filas = _seleccionar(
        "monto,moneda", user_id=user_id, tipo=tipo, categoria=categoria
    )

    totales: dict[Moneda, Decimal] = {}
    for fila in filas:
        moneda = Moneda(fila["moneda"])
        totales[moneda] = totales.get(moneda, Decimal("0")) + _a_decimal(fila["monto"])

    return len(filas), totales


def categorias_frecuentes(
    *, user_id: str, tipo: TipoMovimiento, limite: int = 3, mirar_ultimos: int = 300
) -> tuple[str, ...]:
    """Las etiquetas que el usuario más viene usando, de mayor a menor.

    Es lo que se le ofrece cuando un gasto no encaja en ninguna categoria: el
    parecido letra a letra no sirve para sugerir, y lo que ya usa si.

    Mira solo los ultimos movimientos y no el historial entero: una consulta
    acotada alcanza para saber que usa, y esto corre en medio de una respuesta.
    """
    filas = _seleccionar(
        "categoria",
        user_id=user_id,
        tipo=tipo,
        ordenar_reciente=True,
        limite=mirar_ultimos,
    )

    cuenta: dict[str, int] = {}
    for fila in filas:
        etiqueta = (fila.get("categoria") or "").strip().lower()
        if etiqueta and etiqueta != "otros":
            cuenta[etiqueta] = cuenta.get(etiqueta, 0) + 1

    ordenadas = sorted(cuenta.items(), key=lambda par: (-par[1], par[0]))
    return tuple(nombre for nombre, _ in ordenadas[:limite])


def recategorizar_movimiento(movimiento_id: int, categoria: str, *, user_id: str) -> None:
    """Le cambia la etiqueta a un movimiento ya guardado.

    Es lo que corre cuando el usuario contesta a dónde iba un gasto que el bot
    había dejado en "otros" mientras preguntaba.
    """
    try:
        _obtener_cliente().table(TABLA).update({"categoria": categoria}).eq(
            "id", movimiento_id
        ).eq("user_id", _exigir(user_id)).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la recategorización: %s", detalle)
        raise DBError(f"No pude cambiarle la categoría: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red recategorizando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc


class SinTablaMensajes(DBError):
    """Falta correr migrations/021_mensajes_movimiento.sql.

    Se distingue del resto de los errores porque no es una falla: es una
    migración que todavía no corrió, y el bot tiene que poder seguir andando
    sin editar por reply hasta que corra.
    """


def _es_tabla_faltante(exc: APIError) -> bool:
    """Si el error de PostgREST es «esa tabla no existe»."""
    codigo = getattr(exc, "code", "") or ""
    detalle = (getattr(exc, "message", None) or str(exc)).lower()
    return codigo in {"PGRST205", "42P01"} or "does not exist" in detalle


def anotar_mensaje(
    chat_id: int, message_id: int, movimiento_id: int, *, user_id: str
) -> None:
    """Deja anotado que ese mensaje del bot habla de ese movimiento.

    Upsert y no insert porque Telegram puede reusar un message_id si el mensaje
    anterior se borró, y porque reintentar un update no puede fallar por una
    fila que ya estaba.
    """
    fila = {
        "chat_id": chat_id,
        "message_id": message_id,
        "movimiento_id": movimiento_id,
        "user_id": _exigir(user_id),
    }
    try:
        _obtener_cliente().table(TABLA_MENSAJES).upsert(
            fila, on_conflict="chat_id,message_id"
        ).execute()
    except APIError as exc:
        if _es_tabla_faltante(exc):
            raise SinTablaMensajes(
                "Falta correr migrations/021_mensajes_movimiento.sql."
            ) from exc
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la referencia del mensaje: %s", detalle)
        raise DBError(f"No pude anotar la referencia: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red anotando la referencia del mensaje")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def movimiento_de_mensaje(chat_id: int, message_id: int) -> dict | None:
    """El movimiento del que habla un mensaje del bot, o None si no hay.

    Trae el movimiento entero, no solo el id: quien corrige necesita ver cómo
    está hoy para poder decir cómo queda, y así se evita una segunda consulta.
    """
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_MENSAJES)
            .select(f"movimiento_id, user_id, {TABLA}(*)")
            .eq("chat_id", chat_id)
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        if _es_tabla_faltante(exc):
            raise SinTablaMensajes(
                "Falta correr migrations/021_mensajes_movimiento.sql."
            ) from exc
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la búsqueda de la referencia: %s", detalle)
        raise DBError(f"No pude buscar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red buscando la referencia del mensaje")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    filas = respuesta.data or []
    if not filas:
        return None

    fila = filas[0]
    movimiento = fila.get(TABLA)
    if not movimiento:
        # La referencia quedó pero el movimiento no está. No debería pasar (hay
        # cascade), salvo que alguien borre a mano desde el panel de Supabase.
        logger.info(
            "Referencia huérfana: mensaje %s del chat %s", message_id, chat_id
        )
        return None

    return {
        "movimiento_id": int(fila["movimiento_id"]),
        "user_id": fila["user_id"],
        "movimiento": movimiento,
    }


def obtener_movimiento(movimiento_id: int, *, user_id: str) -> dict | None:
    """Un movimiento por id, siempre acotado a su dueño."""
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA)
            .select("*")
            .eq("id", movimiento_id)
            .eq("user_id", _exigir(user_id))
            .limit(1)
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la lectura del movimiento: %s", detalle)
        raise DBError(f"No pude leer el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red leyendo el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    filas = respuesta.data or []
    return filas[0] if filas else None


# Lo único que se puede tocar de un movimiento ya guardado. El resto (user_id,
# id, objetivo_id) no se corrige por chat: cambiarlos no es «me equivoqué al
# dictarlo», es otra operación.
CAMPOS_EDITABLES = frozenset({
    "fecha", "tipo", "monto", "moneda", "categoria", "descripcion",
    "comercio", "cuenta", "medio_pago",
})


def actualizar_movimiento(
    movimiento_id: int, cambios: dict[str, Any], *, user_id: str
) -> dict:
    """Aplica los cambios y devuelve el movimiento como quedó.

    La lista blanca se aplica acá y no solo en quien llama: es el último lugar
    antes de la base, y lo que se está editando lo propuso un modelo de
    lenguaje a partir de texto libre.
    """
    limpios = {k: v for k, v in (cambios or {}).items() if k in CAMPOS_EDITABLES}
    if not _hay_medio_pago:
        limpios.pop("medio_pago", None)
    if not limpios:
        raise DBError("No hay nada para cambiar.")

    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA)
            .update(limpios)
            .eq("id", movimiento_id)
            .eq("user_id", _exigir(user_id))
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el update del movimiento: %s", detalle)
        raise DBError(f"No pude modificar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red modificando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    filas = respuesta.data or []
    if not filas:
        # El .eq(user_id) no matcheó: o no es suyo, o ya no existe. Las dos
        # cosas se le cuentan igual, para no confirmar que el id existe.
        raise DBError("Ese movimiento ya no está.")
    return filas[0]


def borrar_movimiento(movimiento_id: int, *, user_id: str) -> bool:
    """Borra un movimiento del usuario. False si no había nada que borrar."""
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA)
            .delete()
            .eq("id", movimiento_id)
            .eq("user_id", _exigir(user_id))
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el borrado del movimiento: %s", detalle)
        raise DBError(f"No pude borrar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red borrando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return bool(respuesta.data)


def recategorizar_todos(
    *, user_id: str, tipo: TipoMovimiento, desde: str, hacia: str
) -> int:
    """Mueve todos los movimientos de una etiqueta a otra. Devuelve cuántos."""
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA)
            .update({"categoria": hacia})
            .eq("user_id", _exigir(user_id))
            .eq("tipo", tipo.value)
            .eq("categoria", desde)
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la recategorización masiva: %s", detalle)
        raise DBError(f"No pude mover los movimientos: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red moviendo los movimientos")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return len(respuesta.data or [])


def obtener_objetivos(*, user_id: str, solo_activos: bool = True) -> list[dict]:
    """Los objetivos de ese usuario, para buscar a cuál imputar un ahorro."""
    cliente = _obtener_cliente()
    consulta = (
        cliente.table(TABLA_OBJETIVOS)
        .select("id, nombre, monto_objetivo, moneda, estado")
        .eq("user_id", _exigir(user_id))
    )

    if solo_activos:
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


def crear_objetivo(
    *, user_id: str, nombre: str, monto_objetivo: Decimal, moneda: Moneda
) -> dict:
    """Crea un objetivo a nombre de ese usuario y devuelve la fila."""
    fila = {
        "user_id": _exigir(user_id),
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


def imputar_movimiento(movimiento_id: int, objetivo_id: str, *, user_id: str) -> None:
    """Le asigna un objetivo a un movimiento ya guardado."""
    try:
        _obtener_cliente().table(TABLA).update({"objetivo_id": objetivo_id}).eq(
            "id", movimiento_id
        ).eq("user_id", _exigir(user_id)).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó la imputación: %s", detalle)
        raise DBError(f"No pude imputar el movimiento: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red imputando el movimiento")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def total_imputado(objetivo_id: str, moneda: Moneda, *, user_id: str) -> Decimal:
    """Cuánto se lleva ahorrado para un objetivo, en su moneda."""
    filas = _seleccionar_imputados(objetivo_id, moneda, user_id=user_id)
    return sum((_a_decimal(f["monto"]) for f in filas), Decimal("0"))


def _seleccionar_imputados(
    objetivo_id: str, moneda: Moneda, *, user_id: str
) -> list[dict]:
    cliente = _obtener_cliente()
    try:
        return (
            cliente.table(TABLA)
            .select("monto")
            .eq("user_id", _exigir(user_id))
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


def guardar_movimientos(movimientos: list[Movimiento], *, user_id: str) -> list[int]:
    """Inserta varios movimientos de una y devuelve sus ids, en el mismo orden."""
    if not movimientos:
        return []

    dueno = _exigir(user_id)

    filas = [
        {
            "user_id": dueno,
            "fecha": m.fecha.isoformat(),
            "tipo": m.tipo.value,
            "monto": str(m.monto),
            "moneda": m.moneda.value,
            "categoria": m.categoria,
            "descripcion": m.descripcion,
            "cuenta": m.cuenta,
            "medio_pago": m.medio_pago.value if m.medio_pago else None,
        }
        for m in movimientos
    ]

    creadas = _insertar(filas)
    if len(creadas) != len(movimientos):
        raise DBError("El insert no devolvió todas las filas creadas.")
    return [int(fila["id"]) for fila in creadas]


def guardar_inversion(inversion: Inversion, *, user_id: str) -> str:
    """Inserta una tenencia en `inversiones` y devuelve su id (uuid)."""
    fila = {
        "user_id": _exigir(user_id),
        "tipo": inversion.tipo.value,
        "ticker": inversion.ticker,
        "nombre": inversion.nombre,
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


def crear_alerta(
    alerta: Alerta,
    *,
    user_id: str,
    chat_id: int,
    referencia: Decimal | None,
    moneda: str | None,
) -> dict:
    """Guarda una alerta y devuelve la fila."""
    fila = {
        "user_id": _exigir(user_id),
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
    """Todas las alertas encendidas, de todos los usuarios."""
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


def alertas_de_chat(chat_id: int, *, user_id: str) -> list[dict]:
    """Las alertas activas de un chat, para poder listarlas por Telegram."""
    try:
        return (
            _obtener_cliente()
            .table(TABLA_ALERTAS)
            .select("*")
            .eq("user_id", _exigir(user_id))
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
    """Marca una alerta como disparada."""
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


def borrar_alertas_de_chat(chat_id: int, *, user_id: str) -> int:
    """Apaga todas las de un chat. Devuelve cuántas."""
    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_ALERTAS)
            .update({"activa": False})
            .eq("user_id", _exigir(user_id))
            .eq("chat_id", chat_id)
            .eq("activa", True)
            .execute()
        )
        return len(respuesta.data or [])
    except Exception as exc:
        logger.exception("Error apagando las alertas del chat")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def obtener_recordatorio(chat_id: int, *, user_id: str) -> dict | None:
    """La configuración del chat, o None si nunca la fijó."""
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA_RECORDATORIOS)
            .select("*")
            .eq("user_id", _exigir(user_id))
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        ).data
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude leer el recordatorio: {detalle}") from exc
    except Exception as exc:
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return filas[0] if filas else None


def guardar_recordatorio(
    chat_id: int,
    *,
    user_id: str,
    hora: int | None = None,
    activo: bool | None = None,
    zona_horaria: str | None = None,
) -> dict:
    """Crea o actualiza la configuración del chat."""
    fila: dict[str, Any] = {
        "chat_id": chat_id,
        "user_id": _exigir(user_id),
        "updated_at": "now()",
    }
    if hora is not None:
        fila["hora"] = hora
    if activo is not None:
        fila["activo"] = activo
    if zona_horaria is not None:
        fila["zona_horaria"] = zona_horaria

    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_RECORDATORIOS)
            .upsert(fila, on_conflict="chat_id")
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el upsert del recordatorio: %s", detalle)
        raise DBError(f"No pude guardar el recordatorio: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando el recordatorio")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El upsert no devolvió la fila.")
    return respuesta.data[0]


def recordatorios_activos() -> list[dict]:
    """Todos los recordatorios encendidos, de todos los usuarios."""
    try:
        return (
            _obtener_cliente()
            .table(TABLA_RECORDATORIOS)
            .select("*")
            .eq("activo", True)
            .execute()
        ).data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude leer los recordatorios: {detalle}") from exc
    except Exception as exc:
        raise DBError("No pude comunicarme con la base de datos.") from exc


def marcar_recordatorio_enviado(chat_id: int, fecha_local: date) -> None:
    """Deja constancia del envío para que el mismo día no se repita."""
    try:
        (
            _obtener_cliente()
            .table(TABLA_RECORDATORIOS)
            .update({"ultimo_envio": fecha_local.isoformat()})
            .eq("chat_id", chat_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("No pude marcar el recordatorio de %s como enviado", chat_id)
        raise DBError("No pude registrar el envío del recordatorio.") from exc


def claves_de_items(*, user_id: str, limite: int = 1000) -> list[str]:
    """Las claves de ítem que el usuario ya usó, para agrupar contra ellas."""
    dueno = _exigir(user_id)
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA)
            .select("clave_item")
            .eq("user_id", dueno)
            .not_.is_("clave_item", "null")
            .limit(limite)
            .execute()
        ).data or []
    except Exception:
        logger.warning("No pude leer las claves de ítems", exc_info=True)
        return []

    return sorted({(f.get("clave_item") or "").strip() for f in filas} - {""})


def historial_de_item(clave: str, *, user_id: str, limite: int = 60) -> list[dict]:
    """Las compras anteriores de un ítem, de la más vieja a la más nueva."""
    dueno = _exigir(user_id)
    if not clave:
        return []
    try:
        return (
            _obtener_cliente()
            .table(TABLA)
            .select("fecha,monto,moneda,precio_unitario,categoria")
            .eq("user_id", dueno)
            .eq("clave_item", clave)
            .eq("tipo", TipoMovimiento.GASTO.value)
            .order("fecha")
            .limit(limite)
            .execute()
        ).data or []
    except Exception:
        logger.warning("No pude leer el historial de %r", clave, exc_info=True)
        return []


def movimientos_para_termometro(
    *, user_id: str, desde: date | None = None
) -> list[dict]:
    """Gastos con clave de ítem, para calcular la inflación personal."""
    dueno = _exigir(user_id)
    try:
        consulta = (
            _obtener_cliente()
            .table(TABLA)
            .select("fecha,monto,moneda,categoria,clave_item,precio_unitario,unidad")
            .eq("user_id", dueno)
            .eq("tipo", TipoMovimiento.GASTO.value)
            .not_.is_("clave_item", "null")
            .order("fecha")
        )
        if desde is not None:
            consulta = consulta.gte("fecha", desde.isoformat())
        return consulta.execute().data or []
    except Exception:
        logger.warning("No pude leer los movimientos del termómetro", exc_info=True)
        return []


def reto_activo(chat_id: int, *, user_id: str) -> dict | None:
    """El reto abierto de ese chat, si hay uno."""
    dueno = _exigir(user_id)
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA_RETOS)
            .select("*")
            .eq("user_id", dueno)
            .eq("chat_id", chat_id)
            .eq("estado", "activo")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return filas[0] if filas else None
    except Exception:
        logger.warning("No pude leer el reto activo de %s", chat_id, exc_info=True)
        return None


def crear_reto(
    chat_id: int, *, user_id: str, categoria: str, ahorro_estimado, moneda: str,
    desde: date, hasta: date,
) -> dict:
    """Abre un reto a nombre de ese usuario, para que también lo vea en la web."""
    fila = {
        "user_id": _exigir(user_id),
        "chat_id": chat_id,
        "categoria": categoria,
        "tipo": "sin_gastos",
        "ahorro_estimado": str(ahorro_estimado),
        "moneda": moneda,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "estado": "activo",
    }

    try:
        respuesta = _obtener_cliente().table(TABLA_RETOS).insert(fila).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude crear el reto: {detalle}") from exc
    except Exception as exc:
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data:
        raise DBError("El insert del reto no devolvió la fila.")
    return respuesta.data[0]


def cerrar_reto(reto_id: str, estado: str, gastado) -> None:
    """Marca el reto como cumplido, fallido o abandonado."""
    try:
        (
            _obtener_cliente()
            .table(TABLA_RETOS)
            .update({
                "estado": estado,
                "cerrado_en": datetime.now(timezone.utc).isoformat(),
                "gastado": str(gastado),
            })
            .eq("id", reto_id)
            .execute()
        )
    except Exception:
        logger.warning("No pude cerrar el reto %s", reto_id, exc_info=True)


def gastado_en_reto(reto: dict, *, user_id: str) -> Decimal:
    """Cuánto se gastó del rubro del reto dentro de su ventana."""
    dueno = _exigir(user_id)
    try:
        filas = (
            _obtener_cliente()
            .table(TABLA)
            .select("monto")
            .eq("user_id", dueno)
            .eq("tipo", TipoMovimiento.GASTO.value)
            .eq("categoria", reto["categoria"])
            .eq("moneda", reto.get("moneda", "ARS"))
            .gte("fecha", reto["desde"])
            .lte("fecha", reto["hasta"])
            .execute()
        ).data or []
    except Exception:
        logger.warning("No pude sumar el gasto del reto", exc_info=True)
        return Decimal("0")

    total = Decimal("0")
    for fila in filas:
        try:
            total += Decimal(str(fila["monto"]))
        except Exception:
            continue
    return total


def guardar_inversiones(inversiones: list[Inversion], *, user_id: str) -> list[str]:
    """Inserta varias tenencias de una y devuelve sus ids, en el mismo orden."""
    if not inversiones:
        return []

    dueno = _exigir(user_id)
    filas = [
        {
            "user_id": dueno,
            "tipo": inv.tipo.value,
            "ticker": inv.ticker,
            "nombre": inv.nombre,
            "cantidad": str(inv.cantidad),
            "precio_compra": str(inv.precio_compra),
            "moneda": inv.moneda.value,
            "fecha_compra": inv.fecha_compra.isoformat(),
            "sector": inv.sector,
        }
        for inv in inversiones
    ]

    try:
        respuesta = _obtener_cliente().table(TABLA_INVERSIONES).insert(filas).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el insert múltiple de inversiones: %s", detalle)
        raise DBError(f"No pude guardar las inversiones: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando las inversiones")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data or len(respuesta.data) != len(inversiones):
        raise DBError("El insert de inversiones no devolvió todas las filas.")
    return [str(fila["id"]) for fila in respuesta.data]


def cerrar_inversiones(busqueda: str, *, user_id: str, fecha: date | None = None) -> list[dict]:
    """Marca como cerradas las tenencias activas que coincidan. Nunca borra.

    Busca por ticker exacto primero y por nombre parcial después: «vendí YPF»
    tiene que encontrar tanto el ticker YPFD como el nombre «YPF Sociedad».
    """
    dueno = _exigir(user_id)
    termino = (busqueda or "").strip()
    if not termino:
        raise DBError("No me dijiste qué inversión cerrar.")

    cliente = _obtener_cliente()
    columnas = "id, tipo, ticker, nombre, cantidad, precio_compra, moneda, fecha_compra"

    try:
        filas = (
            cliente.table(TABLA_INVERSIONES)
            .select(columnas)
            .eq("user_id", dueno)
            .eq("activa", True)
            .ilike("ticker", termino)
            .execute()
        ).data or []

        if not filas:
            filas = (
                cliente.table(TABLA_INVERSIONES)
                .select(columnas)
                .eq("user_id", dueno)
                .eq("activa", True)
                .ilike("nombre", f"%{termino}%")
                .execute()
            ).data or []
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude buscar la inversión: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red buscando la inversión a cerrar")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not filas:
        return []

    cierre = (fecha or date.today()).isoformat()
    try:
        (
            cliente.table(TABLA_INVERSIONES)
            .update({"activa": False, "cerrada_en": cierre})
            .in_("id", [f["id"] for f in filas])
            .eq("user_id", dueno)
            .execute()
        )
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude cerrar la inversión: {detalle}") from exc

    logger.info("Cerradas %s tenencias de %s por «%s»", len(filas), dueno, termino)
    return filas


def obtener_inversiones(*, user_id: str, limite: int = 100) -> list[dict]:
    """Las tenencias del usuario. Hoy solo se usa para saber si tiene alguna."""
    dueno = _exigir(user_id)
    try:
        return (
            _obtener_cliente()
            .table(TABLA_INVERSIONES)
            .select("id, tipo, ticker, nombre, cantidad, precio_compra, moneda, fecha_compra")
            .eq("user_id", dueno)
            .eq("activa", True)
            .limit(limite)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.warning("No pude leer las inversiones", exc_info=True)
        return []


def guardar_rendimientos(filas: list[dict]) -> int:
    """Pisa las tasas de las billeteras que vengan. Devuelve cuántas guardó."""
    if not filas:
        return 0

    try:
        respuesta = (
            _obtener_cliente()
            .table(TABLA_RENDIMIENTOS)
            .upsert(filas, on_conflict="nombre")
            .execute()
        )
        return len(respuesta.data or [])
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        raise DBError(f"No pude guardar los rendimientos: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando los rendimientos")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def obtener_rendimientos(*, limite: int = 60) -> list[dict]:
    """Las tasas conocidas, de mayor a menor TNA."""
    try:
        return (
            _obtener_cliente()
            .table(TABLA_RENDIMIENTOS)
            .select("nombre, tipo, tna, tope_monto, fecha_actualizacion, fondo")
            .order("tna", desc=True)
            .limit(limite)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.warning("No pude leer los rendimientos de billeteras", exc_info=True)
        return []


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


def _escapar_like(texto: str) -> str:
    """Deja inertes los comodines de LIKE dentro de un texto del usuario."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def movimientos_para_analisis(
    *,
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
    comercio: str | None = None,
    medio_pago: MedioPago | None = None,
    limite: int = 5000,
) -> list[dict]:
    """Trae las filas crudas que cumplen los filtros, para agregar en Python."""
    cliente = _obtener_cliente()
    filas: list[dict] = []
    offset = 0

    while len(filas) < limite:
        tamano = min(PAGINA, limite - len(filas))
        consulta = _aplicar_filtros(
            cliente.table(TABLA).select(_columnas_analisis()),
            user_id=user_id,
            desde=desde,
            hasta=hasta,
            tipo=tipo,
            moneda=moneda,
            categoria=categoria,
            medio_pago=medio_pago,
        )
        if comercio:
            consulta = consulta.ilike("descripcion", f"%{_escapar_like(comercio.strip().lower())}%")

        consulta = consulta.order("fecha", desc=True).range(offset, offset + tamano - 1)

        try:
            lote = consulta.execute().data or []
        except APIError as exc:
            if _sin_columna_medio_pago(exc):
                # Falta correr 022. Se reintenta la vuelta entera sin la
                # columna en vez de devolver un error: una consulta que no se
                # puede contestar es peor que una sin el desglose por medio.
                _olvidar_medio_pago()
                continue
            detalle = getattr(exc, "message", None) or str(exc)
            logger.error("Supabase rechazó la consulta analítica: %s", detalle)
            raise DBError(f"Error consultando la base: {detalle}") from exc
        except Exception as exc:
            logger.exception("Error de red en la consulta analítica")
            raise DBError("No pude comunicarme con la base de datos.") from exc

        filas.extend(lote)
        if len(lote) < tamano:
            break
        offset += len(lote)

    return filas


def totales_por_moneda(
    *,
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
) -> dict[Moneda, Total]:
    """Suma los montos que cumplen los filtros, separados por moneda."""
    filas = _seleccionar(
        "moneda,monto",
        user_id=user_id,
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
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
) -> list[tuple[str, Moneda, Total]]:
    """Desglosa los totales por categoría, de mayor a menor monto."""
    filas = _seleccionar(
        "categoria,moneda,monto",
        user_id=user_id,
        desde=desde,
        hasta=hasta,
        tipo=tipo,
        moneda=moneda,
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
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    moneda: Moneda | None = None,
) -> dict[Moneda, dict[str, Decimal]]:
    """Ingresos menos gastos, por moneda."""
    ingresos = totales_por_moneda(
        user_id=user_id, desde=desde, hasta=hasta,
        tipo=TipoMovimiento.INGRESO, moneda=moneda,
    )
    gastos = totales_por_moneda(
        user_id=user_id, desde=desde, hasta=hasta,
        tipo=TipoMovimiento.GASTO, moneda=moneda,
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
    user_id: str,
    desde: date | None = None,
    hasta: date | None = None,
    tipo: TipoMovimiento | None = None,
    moneda: Moneda | None = None,
    categoria: str | None = None,
    limite: int = 100,
) -> list[dict]:
    """Consulta movimientos con filtros opcionales, del más reciente al más viejo."""
    filas = _seleccionar(
        "*",
        user_id=user_id,
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
            cuenta=registro.get("cuenta"),
            medio_pago=registro.get("medio_pago"),
        )
        resultados.append(registro)
    return resultados
