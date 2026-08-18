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

EL user_id NO ES OPCIONAL
El bot se conecta con la clave service_role, que SALTEA RLS. Las policies que
aíslan a los usuarios en el navegador acá no corren: para PostgREST con esa
clave, la tabla `movimientos` es una sola tabla con los movimientos de todos.

Por eso cada función que toca datos de alguien lleva `user_id` como parámetro
OBLIGATORIO y de solo palabra clave. Es a propósito que no tenga default:

- Sin default, olvidarse de pasarlo es un TypeError al llamar, no una consulta
  silenciosa que devuelve la base entera.
- De solo palabra clave, no se puede pasar de casualidad en la posición
  equivocada.

La regla, entonces: si una función de este módulo lee o escribe algo de un
usuario, su `user_id` viaja en la llamada. Las únicas excepciones —las de los
crons, que trabajan sobre todos los usuarios a la vez— están marcadas una por
una en su docstring.
"""

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


def _exigir(user_id: str) -> str:
    """Devuelve el user_id, o rompe si vino vacío.

    Parece de más, porque las firmas ya lo exigen. No lo es: el valor puede
    venir de un dict, de un JSON o de una fila, y ahí `None` o `""` pasan sin
    que nadie se dé cuenta. Un `.eq("user_id", None)` no explota: PostgREST lo
    manda como el texto "None", no matchea nada y la consulta devuelve una
    lista vacía. Ese es el peor final posible —el usuario ve todo en cero y
    cree que perdió los datos—, así que se corta acá con un error que dice qué
    pasó.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise DBError(
            "Falta el user_id: no se puede leer ni escribir sin saber de quién "
            "son los datos."
        )
    return user_id.strip()


# --------------------------------------------------------------------------
# Identidad: de un chat de Telegram a un usuario de Supabase
# --------------------------------------------------------------------------
#
# Las dos únicas lecturas que NO llevan user_id, porque son justamente las que
# lo averiguan. Sobre ellas se apoya app/usuarios.py, que agrega el caché y la
# decisión de habilitar o no.


def vinculo_de_chat(chat_id: int) -> dict | None:
    """La fila de `usuarios_telegram` de ese chat, o None si no está vinculado.

    None significa "este chat no es de nadie". Un error de red, en cambio,
    levanta DBError: no es lo mismo saber que no hay vínculo que no haber
    podido preguntar, y confundirlos dejaría a un usuario legítimo afuera —o,
    peor, invitaría a tratar el error como "seguí igual".
    """
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
        # 42P01 = la tabla no existe: falta correr migrations/009.
        logger.error("Supabase rechazó la consulta del vínculo: %s", detalle)
        raise DBError(f"No pude leer el vínculo del chat: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red consultando el vínculo del chat")
        raise DBError("No pude comunicarme con la base de datos.") from exc

    return filas[0] if filas else None


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
    """Encadena sobre la query solo los filtros que vengan definidos.

    El de user_id no es "solo si viene": va SIEMPRE y va primero. Es el único
    que no depende de lo que haya preguntado el usuario, porque no acota la
    respuesta: define de quién es la pregunta.
    """
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
        # Las categorías se guardan ya normalizadas en minúsculas.
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

    # Las dos tablas de las que ahora depende el control de acceso. Si falta
    # alguna, el bot no puede saber de quién es ningún mensaje, y conviene
    # enterarse al arrancar y no cuando el primer usuario escriba y reciba un
    # "no tengo tu acceso habilitado" que no es cierto.
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
    """Inserta un Movimiento y devuelve el id asignado.

    `created_at` lo pone Postgres solo (DEFAULT now()).

    `objetivo_id` se pasa cuando el ahorro ya se pudo imputar en el momento. Si
    hay que preguntar primero, el movimiento se guarda igual sin él y después
    se imputa con `imputar_movimiento`: la plata se apartó, y perder el
    registro por una duda sobre a qué objetivo va sería el peor negocio.

    El `user_id` va explícito: la columna es NOT NULL y su default auth.uid()
    no se completa con service_role, que es como escribe el bot.
    """
    fila = {
        "user_id": _exigir(user_id),
        "fecha": movimiento.fecha.isoformat(),
        "tipo": movimiento.tipo.value,
        # str() y no float(): el JSON sale con el decimal exacto y Postgres
        # lo castea a numeric sin pasar por punto flotante.
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
# 1. Al leer ve los objetivos de TODOS los usuarios. El `.eq("user_id", ...)`
#    de cada consulta es lo único que lo impide: no hay red de contención
#    abajo, porque RLS no corre para esta clave.
# 2. Al insertar, el `default auth.uid()` de la columna user_id devuelve null
#    —no hay sesión de nadie—, y la columna es NOT NULL. Así que el user_id hay
#    que mandarlo explícito o el insert falla.


def obtener_objetivos(*, user_id: str, solo_activos: bool = True) -> list[dict]:
    """Los objetivos de ese usuario, para buscar a cuál imputar un ahorro."""
    cliente = _obtener_cliente()
    consulta = (
        cliente.table(TABLA_OBJETIVOS)
        .select("id, nombre, monto_objetivo, moneda, estado")
        .eq("user_id", _exigir(user_id))
    )

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
    """Le asigna un objetivo a un movimiento ya guardado.

    El `.eq("user_id", ...)` acota el UPDATE al dueño. El id del movimiento sale
    de una pregunta abierta en memoria, que es por chat, así que en la práctica
    ya es suyo; el filtro está igual porque un UPDATE por id sin acotar es la
    clase de consulta que un día se copia a otro lado donde el id sí viene de
    afuera.
    """
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
    """Cuánto se lleva ahorrado para un objetivo, en su moneda.

    El filtro por moneda no es un detalle: un aporte de US$400 imputado a una
    meta en pesos sumaría 400 sobre 500.000.
    """
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


# --------------------------------------------------------------------------
# Inversiones
# --------------------------------------------------------------------------


def guardar_movimientos(movimientos: list[Movimiento], *, user_id: str) -> list[int]:
    """Inserta varios movimientos de una y devuelve sus ids, en el mismo orden.

    Un solo INSERT en vez de N: para un mensaje con cinco gastos, la diferencia
    es un viaje a Supabase contra cinco.

    Postgres corre el INSERT múltiple como una sola sentencia, así que o entran
    todos o no entra ninguno. Eso es lo que se quiere: media lista guardada
    dejaría al usuario sin saber cuáles quedaron.
    """
    if not movimientos:
        return []

    # Todos a nombre de quien mandó el mensaje: un mensaje viene de un chat, y
    # un chat es de un solo usuario.
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
    """Inserta una tenencia en `inversiones` y devuelve su id (uuid).

    El `user_id` va explícito: el default auth.uid() de la tabla no se completa
    con service_role, que es como escribe el bot.
    """
    fila = {
        "user_id": _exigir(user_id),
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
    user_id: str,
    chat_id: int,
    referencia: Decimal | None,
    moneda: str | None,
) -> dict:
    """Guarda una alerta y devuelve la fila.

    `referencia` es el precio del momento: contra él se miden después los
    porcentajes. Se guarda al crear y no se recalcula, para que "baja 5%"
    signifique siempre 5% desde que la pediste.

    Van los dos, user_id y chat_id, y no es redundante: el user_id es de quién
    es la alerta (y con qué se filtra), el chat_id es adónde mandar el aviso
    cuando suene, que puede pasar sin nadie conectado.
    """
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
    """Todas las alertas encendidas, de todos los usuarios.

    EXCEPCIÓN a la regla del user_id, y de las tres que hay es la más fácil de
    leer mal. Sin filtrar por usuario a propósito: la corrida del cron no la
    pide nadie en particular, revisa las de todos. Por eso el endpoint que la
    dispara va protegido por un secreto y no por una sesión.

    Que no se filtre acá no mezcla datos de nadie: cada fila se responde a SU
    chat_id, el que quedó guardado al crearla. Lo que no puede hacer nunca esta
    función es alimentar una respuesta a un mensaje entrante.
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


def alertas_de_chat(chat_id: int, *, user_id: str) -> list[dict]:
    """Las alertas activas de un chat, para poder listarlas por Telegram.

    Filtra por los dos. Con chat_id solo alcanzaría mientras un chat pertenezca
    siempre al mismo usuario; si un chat se revincula a otra cuenta, el dueño
    nuevo vería las alertas del anterior.
    """
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


# --------------------------------------------------------------------------
# Recordatorio diario
# --------------------------------------------------------------------------


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
    """Crea o actualiza la configuración del chat.

    Un upsert por `chat_id`, que es la clave primaria: fijar la hora dos veces
    pisa la anterior en vez de dejar dos filas que mandarían dos mensajes.

    El user_id viaja en el upsert, así que si un chat se revincula a otra
    cuenta, la fila pasa a ser del dueño nuevo en la primera corrida. Sin él el
    insert fallaría: la columna quedó NOT NULL en migrations/009.
    """
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
    """Todos los recordatorios encendidos, de todos los usuarios.

    EXCEPCIÓN a la regla del user_id, por lo mismo que `alertas_activas`: la
    dispara un cron, no una persona, y cada aviso sale al chat_id de su propia
    fila. No alimenta ninguna respuesta a un mensaje entrante.

    El filtro por hora NO se hace en SQL: cada fila tiene su propia zona
    horaria, así que "son las 21" depende de cuál. La comparación se hace en
    Python, que es donde está el calendario. Son pocas filas.
    """
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
    """Deja constancia del envío para que el mismo día no se repita.

    La tercera y última EXCEPCIÓN: la llama el mismo cron, sobre la fila que
    acaba de usar, y `chat_id` es la clave primaria de la tabla. No lee nada
    que después se le muestre a nadie.
    """
    try:
        (
            _obtener_cliente()
            .table(TABLA_RECORDATORIOS)
            .update({"ultimo_envio": fecha_local.isoformat()})
            .eq("chat_id", chat_id)
            .execute()
        )
    except Exception as exc:
        # Si esto falla, el aviso ya salió: se registra y se sigue. El riesgo
        # es un mensaje repetido dentro de la misma hora, no perder el envío.
        logger.exception("No pude marcar el recordatorio de %s como enviado", chat_id)
        raise DBError("No pude registrar el envío del recordatorio.") from exc


def claves_de_items(*, user_id: str, limite: int = 1000) -> list[str]:
    """Las claves de ítem que el usuario ya usó, para agrupar contra ellas.

    Filtrar acá no es solo privacidad: las claves ajenas cambiarían cómo se
    agrupan las propias, y el termómetro de inflación de uno se movería por lo
    que compró otro.

    `_exigir` va AFUERA del try a propósito: adentro, el `except Exception`
    convertiría "no sé de quién es" en "no tiene ninguna", que es justo la
    confusión que este módulo tiene que impedir. Mismo criterio en las demás
    funciones de acá que degradan a un valor vacío.
    """
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
        # Sin las conocidas, el ítem entra con su clave normalizada y listo:
        # se agrupa peor, pero no se pierde el movimiento.
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


# --------------------------------------------------------------------------
# Retos de ahorro
# --------------------------------------------------------------------------


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
    """Las tenencias del usuario. Hoy solo se usa para saber si tiene alguna.

    Devuelve [] ante cualquier error en vez de propagar: quien la llama la usa
    para decidir si agrega una línea a un mensaje, y no vale la pena tirar
    abajo la respuesta entera por eso.

    Ojo con ese [] cuando se toca esta función: acá "no pude leer" y "no tiene
    ninguna" terminan igual, y está bien porque el peor caso es una línea de
    menos en un mensaje. El filtro por user_id va ANTES del try, así que un
    user_id vacío levanta DBError en vez de caer en el except y devolver [].
    """
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


# --------------------------------------------------------------------------
# Rendimientos de billeteras virtuales
# --------------------------------------------------------------------------
#
# La única tabla sin user_id: una TNA es pública e igual para todos. Las escribe
# el cron con service_role y la web las lee directo de Supabase.


def guardar_rendimientos(filas: list[dict]) -> int:
    """Pisa las tasas de las billeteras que vengan. Devuelve cuántas guardó.

    Es un UPSERT por `nombre`, no un delete-and-insert. La diferencia importa: si
    la fuente devolviera hoy la mitad de las billeteras, borrar primero dejaría a
    la otra mitad sin ninguna tasa. Así, las que no vinieron conservan la fila
    anterior con su fecha vieja, y la pantalla la muestra como vieja.

    Por el mismo motivo acá no hay ninguna función que borre.
    """
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
        # 42P01 = la tabla no existe: falta correr migrations/008.
        raise DBError(f"No pude guardar los rendimientos: {detalle}") from exc
    except Exception as exc:
        logger.exception("Error de red guardando los rendimientos")
        raise DBError("No pude comunicarme con la base de datos.") from exc


def obtener_rendimientos(*, limite: int = 60) -> list[dict]:
    """Las tasas conocidas, de mayor a menor TNA.

    Devuelve [] ante cualquier error en vez de propagar: quien la llama arma un
    mensaje de Telegram, y una tabla de tasas caída no puede dejar al usuario
    sin respuesta.
    """
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
    r"""Deja inertes los comodines de LIKE dentro de un texto del usuario.

    Sin esto, buscar el comercio "100%" traería todo, y "_" haría de comodín
    de un carácter. No es una inyección —el valor viaja como parámetro, no
    concatenado—, pero sí un resultado equivocado y silencioso.
    """
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
    """Trae las filas crudas que cumplen los filtros, para agregar en Python.

    Los filtros son un conjunto FIJO de parámetros con nombre. No hay forma de
    pasar un fragmento de consulta: cada valor se entrega a PostgREST con
    `.eq()` / `.gte()` / `.ilike()`, que lo mandan como parámetro.

    `limite` es un techo de seguridad: una pregunta sin acotar sobre años de
    historia no puede traer la base entera a memoria.
    """
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
            # ilike y no eq: "café" tiene que encontrar "café de la esquina".
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
    """Suma los montos que cumplen los filtros, separados por moneda.

    Nunca mezcla ARS con USD: sumar monedas distintas daría un número sin
    ningún significado. Devuelve solo las monedas que tienen movimientos.
    """
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
    """Desglosa los totales por categoría, de mayor a menor monto.

    Cada entrada es (categoria, moneda, Total). Una misma categoría aparece
    una vez por cada moneda en la que haya movimientos.
    """
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
    """Ingresos menos gastos, por moneda.

    Ahorro e inversión quedan afuera del balance a propósito: esa plata sigue
    siendo tuya, solo cambió de lugar. Contarla como gasto daría un balance
    falsamente negativo.
    """
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
    """Consulta movimientos con filtros opcionales, del más reciente al más viejo.

    Devuelve dicts (no Movimiento) para conservar `id` y `created_at`, que no
    forman parte del modelo. La clave "movimiento" trae el objeto ya validado.
    """
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
            # .get() y no [...]: si todavía no se corrió el ALTER TABLE, la
            # columna no viene en la respuesta y leer movimientos viejos no
            # tiene por qué romperse.
            cuenta=registro.get("cuenta"),
        )
        resultados.append(registro)
    return resultados
