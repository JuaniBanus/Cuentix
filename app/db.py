"""Persistencia en Supabase (Postgres), vía la API REST de PostgREST."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from postgrest import APIError
from supabase import Client, create_client

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.models import Alerta, Inversion, Moneda, Movimiento, TipoMovimiento

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
        }
        for m in movimientos
    ]

    try:
        respuesta = _obtener_cliente().table(TABLA).insert(filas).execute()
    except APIError as exc:
        detalle = getattr(exc, "message", None) or str(exc)
        logger.error("Supabase rechazó el insert múltiple: %s", detalle)
        raise DBError(f"No pude guardar los movimientos: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando los movimientos")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    if not respuesta.data or len(respuesta.data) != len(movimientos):
        raise DBError("El insert no devolvió todas las filas creadas.")
    return [int(fila["id"]) for fila in respuesta.data]


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


def obtener_inversiones(*, user_id: str, limite: int = 100) -> list[dict]:
    """Las tenencias del usuario. Hoy solo se usa para saber si tiene alguna."""
    dueno = _exigir(user_id)
    try:
        return (
            _obtener_cliente()
            .table(TABLA_INVERSIONES)
            .select("id, tipo, ticker, nombre, cantidad, precio_compra, moneda, fecha_compra")
            .eq("user_id", dueno)
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
    limite: int = 5000,
) -> list[dict]:
    """Trae las filas crudas que cumplen los filtros, para agregar en Python."""
    cliente = _obtener_cliente()
    filas: list[dict] = []
    offset = 0

    while len(filas) < limite:
        tamano = min(PAGINA, limite - len(filas))
        consulta = _aplicar_filtros(
            cliente.table(TABLA).select("fecha,tipo,monto,moneda,categoria,descripcion,cuenta"),
            user_id=user_id,
            desde=desde,
            hasta=hasta,
            tipo=tipo,
            moneda=moneda,
            categoria=categoria,
        )
        if comercio:
            consulta = consulta.ilike("descripcion", f"%{_escapar_like(comercio.strip().lower())}%")

        consulta = consulta.order("fecha", desc=True).range(offset, offset + tamano - 1)

        try:
            lote = consulta.execute().data or []
        except APIError as exc:
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
        )
        resultados.append(registro)
    return resultados
