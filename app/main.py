"""App FastAPI: recibe los updates de Telegram, registra movimientos y responde consultas."""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import pendientes
from app.analitica import ejecutar as ejecutar_plan
from app.asesor import analizar as analizar_compra
from app.asesor import redactar as redactar_analisis
from app.analitica import redactar as redactar_plan
from app.cartera import rendimiento as rendimiento_cartera
from app.comandos import respuesta_directa
from app.cuotas import comparar as comparar_cuotas
from app.cuotas import pedir_faltantes as pedir_faltantes_cuotas
from app.cuotas import redactar as redactar_cuotas
from app.tasas import obtener as obtener_tasas
from app.config import ALERTAS_SECRET, CHATS_PERMITIDOS, ORIGENES_WEB, WEBHOOK_SECRET
from app.cupos import CupoAgotado, barriendo
from app.cupos import consumir as consumir_cupo
from app.cupos import global_hoy as consumo_global_hoy
from app.cupos import restante as cupo_restante
from app.limites import Limite, LimiteExcedido, identificar
from app.alertas import revisar as revisar_alertas_de_precio
from app.insights import AgregadosGastos, InsightsError
from app.insights import generar as generar_insights
from app.mercado import MercadoError, SinClave, ValorInvalido
from app.mercado import cerrar_cliente as cerrar_cliente_mercado
from app.mercado import historico as historico_de_mercado
from app.mercado import indice as indice_de_mercado
from app.mercado import costo_lote, precios as precios_de_mercado
from app.mercado import precio as precio_de_mercado
from app.mercado import presupuesto as presupuesto_mercado
from app.sesion_web import CuentaInactiva, SesionInvalida
from app.sesion_web import cerrar_cliente as cerrar_cliente_sesion
from app.sesion_web import verificar as verificar_sesion
from app.inflacion import detectar_salto
from app.items import clave_para
from app.narrativa import AgregadosMes, NarrativaError
from app.narrativa import generar as generar_narrativa
from app.recurrentes import detectar as detectar_recurrentes
from app.recurrentes import redactar as redactar_recurrentes
from app.rendimientos import actualizar as actualizar_rendimientos
from app.retos import DURACION_DIAS as DURACION_RETO
from app.retos import (
    proponer as proponer_reto,
    revisar as revisar_reto,
    texto_activo,
    texto_aceptado,
    texto_cumplido,
    texto_fallido,
    texto_propuesta,
    texto_sin_propuesta,
)
from app.db import (
    DBError,
    Total,
    alertas_de_chat,
    balance,
    borrar_categoria,
    cerrar_reto,
    crear_alerta,
    claves_de_items,
    categorias_frecuentes,
    crear_categoria,
    crear_objetivo,
    crear_reto,
    gastado_en_reto,
    obtener_categorias,
    recategorizar_movimiento,
    recategorizar_todos,
    reto_activo,
    historial_de_item,
    movimientos_para_termometro,
    cerrar_inversiones,
    guardar_inversion,
    guardar_inversiones,
    guardar_movimiento,
    guardar_movimientos,
    imputar_movimiento,
    init_db,
    obtener_inversiones,
    obtener_objetivos,
    obtener_rendimientos,
    pausar_cuenta as pausar_cuenta_db,
    total_imputado,
    totales_por_categoria,
    totales_por_moneda,
    uso_de_categoria,
)
from app.categorias import (
    Categoria,
    Vocabulario,
    formatear_listado,
    leer_comando as leer_comando_categorias,
    leer_creacion,
)
from app.models import (
    AccionCategoria,
    Alerta,
    CompraHipotetica,
    Consulta,
    Financiacion,
    GestionCategoria,
    Intencion,
    Inversion,
    Moneda,
    Movimiento,
    PlanConsulta,
    TipoAlerta,
    TipoInversion,
    TipoMovimiento,
)
from app.objetivos import buscar, normalizar, parsear_monto, progreso
from app.parser import (
    Interpretacion,
    ParserError,
    ServicioNoDisponible,
    interpretar_mensaje,
)
from app.usuarios import Usuario
from app.usuarios import resolver as resolver_usuario
from app.recordatorio import atender_comando as atender_comando_recordatorio
from app.recordatorio import enviar_recordatorios
from app.recordatorio import es_comando as es_comando_recordatorio
from app.telegram import (
    ArchivoDemasiadoGrande,
    TelegramError,
    cerrar_cliente,
    descargar_archivo,
    enviar_mensaje,
    extraer_chat_id,
    extraer_mensaje,
    extraer_voz,
)
from app.telegram import VozEntrante
from app.transcripcion import (
    TOPE_BYTES as TOPE_AUDIO_BYTES,
    TOPE_SEGUNDOS as TOPE_AUDIO_SEGUNDOS,
    AudioMuyLargo,
    Problema,
    Transcripcion,
)
from app.transcripcion import transcribir as transcribir_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MSG_SOLO_TEXTO = (
    "Por ahora entiendo texto y audios 🙃\n"
    "Escribime o mandame un audio: «gasté 8 lucas en el super ayer»."
)

# El eco de un audio que se entendio bien. No frena nada: el bot lo manda y
# sigue anotando. Esta para que el usuario vea que se entendio incluso cuando
# el modelo se declara seguro, que es justo el caso en que un error pasaria
# desapercibido hasta leer la confirmacion del movimiento.
MSG_ESCUCHE = "🎤 Escuché: «{texto}»"

MSG_AUDIO_LARGO = (
    f"Ese audio es muy largo para mí 😅 (aguanto hasta "
    f"{TOPE_AUDIO_SEGUNDOS // 60} minutos).\n"
    "Mandame uno más cortito con el gasto, o escribímelo."
)

MSG_AUDIO_PESADO = (
    "Ese audio pesa demasiado y no lo pude bajar 😅\n"
    "Probá con uno más corto, o escribímelo."
)

MSG_AUDIO_VACIO = (
    "No llegué a escuchar nada en ese audio 🤔\n"
    "¿Lo grabás de nuevo? A veces se corta el micrófono."
)

MSG_AUDIO_INAUDIBLE = (
    "Se escucha, pero no llego a entender qué decís 😕\n"
    "Si estás en la calle suele ser el ruido de fondo.\n"
    "Probá de nuevo en un lugar más tranquilo, o escribímelo."
)

MSG_AUDIO_NO_ES_PLATA = (
    "Te escuché bien, pero no encontré ningún gasto ni pregunta ahí 🙃\n"
    "¿Me lo mandaste por error?"
)

MSG_AUDIO_FALLO = (
    "No pude bajar tu audio de Telegram 😬\n"
    "Probá de nuevo en un ratito, o escribímelo."
)

MSG_AUDIO_CANCELADO = (
    "Listo, no anoto nada 👍\n"
    "Escribímelo y lo registro."
)

MSG_MUCHOS_AUDIOS = (
    "Estás mandando muchos audios seguidos 😅\n"
    "Escuchar cada uno me consume cuota, así que dejame respirar un rato.\n"
    "Mientras tanto, escribímelo y lo anoto al toque."
)
MSG_NO_ENTENDI = (
    "No entendí 🤔\n"
    "Podés anotar algo: «pagué 45 mil de luz»\n"
    "o preguntarme: «¿cuánto gasté este mes?»\n\n"
    "Escribí /ayuda para ver todo lo que puedo hacer."
)
MSG_ERROR_INTERNO = "Se me rompió algo 😬 Probá de nuevo en un ratito."

MSG_SERVICIO_CAIDO = (
    "Ahora mismo no puedo leer los mensajes 😵‍💫\n"
    "El servicio que uso para entenderte está saturado.\n"
    "Mandámelo de nuevo en un minuto y lo anoto."
)

MSG_SIN_ACCESO = (
    "No tengo tu acceso habilitado 🔒\n"
    "Contactá al administrador para que te dé de alta.\n\n"
    "Tu número de chat es {chat_id}"
)

ESPERA_SIN_ACCESO = 30 * 60.0
_ultimo_aviso: dict[int, float] = {}

TOPE_AVISOS = 2_000

_aviso_webhook_viejo = False

TOPE_CATEGORIAS = 8

# Cuántas categorías propias puede tener un usuario. Es un techo generoso: con
# más de esto la lista deja de servir para elegir y el prompt se infla al pedo.
TOPE_PROPIAS = 60

LIMITE_MERCADO = Limite(30, 60.0, "mercado")
LIMITE_GEMINI = Limite(20, 3600.0, "gemini")

# Cada audio gasta una llamada a Gemini de mas que un mensaje escrito: primero
# se transcribe y despues se interpreta. El tope es por chat y existe para que
# una racha de audios no se lleve puesta la cuota diaria de todos.
LIMITE_AUDIO = Limite(20, 3600.0, "audio")


def _frenar(limite: Limite, clave: str) -> None:
    """Aplica un cupo y traduce el exceso a un 429 con Retry-After."""
    try:
        limite.revisar(clave)
    except LimiteExcedido as exc:
        logger.warning("Cupo de %s agotado por %s", limite.nombre, clave)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.espera)},
        ) from exc


async def _exigir_sesion(authorization: str | None, activo: bool = False) -> str:
    """El id del usuario dueño del token, o un 401 con el motivo."""
    try:
        return await verificar_sesion(authorization, exigir_activo=activo)
    except CuentaInactiva as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except SesionInvalida as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


def _cobrar(user_id: str, unidades: int, tickers: list[str]) -> None:
    """Registra el pedido y cobra las unidades que gaste, o corta con un 429.

    Se registra aunque cueste cero: el mercado argentino es gratis y el caché
    también, y son justo los casos donde un barrido no dejaría rastro.
    """
    try:
        consumir_cupo(user_id, unidades, refrescos=0, tickers=tickers)
    except CupoAgotado as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "3600"}
        ) from exc


async def _pausar_por_abuso(user_id: str, estado: dict) -> None:
    """Pausa la cuenta que barre tickers en vez de mirar su portafolio."""
    if not barriendo(estado):
        return
    logger.warning("Patrón de barrido en %s: %s tickers distintos hoy",
                   user_id, estado.get("tickers"))
    try:
        pausar_cuenta_db(user_id, 'barrido de tickers')
    except Exception:
        logger.exception("No pude pausar la cuenta %s", user_id)


def _autorizar_tarea(authorization: str | None) -> None:
    """Comprueba el secreto de los cron, que viaja en la cabecera."""
    if not ALERTAS_SECRET:
        logger.warning("Disparo de tarea con ALERTAS_SECRET sin configurar")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

    entregado = ""
    if authorization and authorization.lower().startswith("bearer "):
        entregado = authorization[7:].strip()

    if not secrets.compare_digest(entregado, ALERTAS_SECRET):
        logger.warning("Disparo de tarea con secreto inválido")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y apagado de la app."""
    init_db()
    logger.info("Base de datos lista")

    if CHATS_PERMITIDOS:
        logger.warning(
            "CHATS_PERMITIDOS tiene %s chat(s): además de estar en "
            "usuarios_telegram, hay que estar en esa lista. Vaciala para que "
            "mande solo la tabla.",
            len(CHATS_PERMITIDOS),
        )
    else:
        logger.info("Acceso por usuarios_telegram (CHATS_PERMITIDOS vacío)")

    yield
    await cerrar_cliente()
    await cerrar_cliente_sesion()
    await cerrar_cliente_mercado()
    logger.info("Clientes HTTP cerrados")


app = FastAPI(title="Agente Cuenta", lifespan=lifespan)

if ORIGENES_WEB:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ORIGENES_WEB),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
else:
    logger.warning(
        "ORIGENES_WEB está vacío: el panel de insights de la web no va a poder "
        "llamar al backend. Definí los orígenes permitidos en el .env."
    )


@app.get("/")
async def salud() -> dict[str, str]:
    """Chequeo de vida, para monitoreo o para ver que levantó bien."""
    return {"status": "ok"}


@app.get("/api/precios")
async def api_precios(
    tickers: str,
    request: Request,
    mercados: str = "",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Precios de todo un portafolio en un solo pedido.

    `tickers` es una lista separada por comas y `mercados` la lista paralela de
    mercados; si falta, se asume «us» para todos. Cada llamada cuenta como una
    actualización del cupo diario del usuario.
    """
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_MERCADO, identificar(request))

    lista = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not lista:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pediste ningún ticker.")

    columnas = [m.strip().lower() or "us" for m in mercados.split(",")] if mercados else []
    pedidos = [(t, columnas[i] if i < len(columnas) else "us") for i, t in enumerate(lista)]

    unidades = costo_lote(pedidos)
    aviso = None
    solo_cache = False

    try:
        estado = consumir_cupo(usuario, unidades, refrescos=1 if unidades else 0, tickers=lista)
        await _pausar_por_abuso(usuario, estado)
    except CupoAgotado as exc:
        logger.info("Cupo agotado para %s (%s)", usuario, exc.motivo)
        aviso, solo_cache = str(exc), True

    try:
        datos = await precios_de_mercado(pedidos, solo_cache=solo_cache)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return {**datos, "aviso": aviso, "cupo": cupo_restante(usuario)}


@app.get("/api/precio")
async def api_precio(
    ticker: str,
    request: Request,
    mercado: str = "us",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Precio actual, variación diaria/semanal/mensual y máximos y mínimos."""
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_MERCADO, identificar(request))
    _cobrar(usuario, costo_lote([(ticker, mercado)]), [ticker])

    try:
        return await precio_de_mercado(ticker, mercado)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.get("/api/historico")
async def api_historico(
    ticker: str,
    request: Request,
    mercado: str = "us",
    dias: int = 90,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Cierres diarios de un activo, del más viejo al más nuevo."""
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_MERCADO, identificar(request))
    _cobrar(usuario, 0 if mercado == "ar" else 1, [ticker])

    try:
        return await historico_de_mercado(ticker, mercado, dias)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.get("/api/indice")
async def api_indice(
    symbol: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Valor de un índice. Acepta ^GSPC (S&P 500) y ^MERV (Merval)."""
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_MERCADO, identificar(request))
    _cobrar(usuario, 2, [symbol])

    try:
        return await indice_de_mercado(symbol)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.post("/tareas/alertas")
async def revisar_alertas(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Revisa las alertas de precio y avisa las que se cumplieron."""
    _autorizar_tarea(authorization)
    return await revisar_alertas_de_precio()


@app.post("/narrativa")
async def escribir_narrativa(
    datos: AgregadosMes,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Redacta el resumen del mes a partir de agregados."""
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_GEMINI, usuario)

    try:
        texto = await run_in_threadpool(generar_narrativa, datos)
    except NarrativaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return {"texto": texto}


@app.post("/tareas/recordatorios")
async def disparar_recordatorios(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Manda el recordatorio diario a quien le toque en esta hora."""
    _autorizar_tarea(authorization)
    return await enviar_recordatorios()


@app.post("/tareas/rendimientos")
async def actualizar_tasas_billeteras(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Refresca las TNA de las billeteras virtuales desde la fuente pública."""
    _autorizar_tarea(authorization)
    return await run_in_threadpool(actualizar_rendimientos)


@app.get("/api/cuota")
async def api_cuota(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Cuánto queda del cupo diario del proveedor. Para poder monitorearlo."""
    usuario = await _exigir_sesion(authorization, activo=True)
    return {
        "global": consumo_global_hoy(),
        "usuario": cupo_restante(usuario),
        "proceso": presupuesto_mercado(),
    }


@app.post("/insights")
async def analizar_gastos(
    datos: AgregadosGastos,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, list]:
    """Interpreta agregados de gasto y devuelve observaciones."""
    usuario = await _exigir_sesion(authorization, activo=True)
    _frenar(LIMITE_GEMINI, usuario)

    try:
        insights = await run_in_threadpool(generar_insights, datos)
    except InsightsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return {"insights": [i.model_dump() for i in insights]}


async def _recibir_update(request: Request, tareas: BackgroundTasks) -> dict[str, bool]:
    """Encola el update. Lo comparten las dos rutas del webhook."""
    try:
        update = await request.json()
    except ValueError:
        logger.warning("Update con body que no es JSON")
        return {"ok": True}

    tareas.add_task(procesar_update, update)
    return {"ok": True}


@app.post("/webhook")
async def webhook(
    request: Request,
    tareas: BackgroundTasks,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """Punto de entrada de los updates de Telegram, con el secreto en cabecera."""
    if not secrets.compare_digest(x_telegram_bot_api_secret_token or "", WEBHOOK_SECRET):
        logger.warning("Webhook llamado con secreto inválido desde %s", request.client)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return await _recibir_update(request, tareas)


@app.post("/webhook/{secret}")
async def webhook_en_ruta(
    secret: str,
    request: Request,
    tareas: BackgroundTasks,
) -> dict[str, bool]:
    """La forma vieja: el secreto en la URL. Sigue viva para no cortar el bot."""
    if not secrets.compare_digest(secret, WEBHOOK_SECRET):
        logger.warning("Webhook llamado con secreto inválido desde %s", request.client)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    global _aviso_webhook_viejo
    if not _aviso_webhook_viejo:
        _aviso_webhook_viejo = True
        logger.warning(
            "El webhook sigue usando el secreto en la RUTA, que queda escrito "
            "en el log de accesos. Volvé a registrarlo con secret_token para "
            "que viaje en la cabecera."
        )

    return await _recibir_update(request, tareas)


async def procesar_update(update: Any) -> None:
    """Trabajo pesado, fuera del ciclo request/response."""
    chat_id = extraer_chat_id(update)
    if chat_id is None:
        logger.debug(
            "Update sin chat: %s",
            list(update) if isinstance(update, dict) else type(update),
        )
        return

    usuario = await _autorizar(chat_id)
    if usuario is None:
        return

    entrante = extraer_mensaje(update)
    voz = extraer_voz(update) if entrante is None else None

    if entrante is None and voz is None:
        logger.info("Update sin texto ni audio en el chat %s", chat_id)
        await _responder(chat_id, MSG_SOLO_TEXTO)
        return

    chat_del_mensaje = entrante.chat_id if entrante is not None else voz.chat_id
    if chat_del_mensaje != chat_id:
        logger.error(
            "Update inconsistente: autoricé el chat %s y el mensaje dice %s",
            chat_id, chat_del_mensaje,
        )
        return

    if entrante is not None:
        texto = entrante.texto
    else:
        # Recién acá se baja el archivo y se gasta cuota: primero el chat tenía
        # que estar autorizado y ser el mismo que dice el update.
        texto = await _escuchar_audio(chat_id, voz)
        if texto is None:
            return

    logger.info("Mensaje de %s (%s): %r", chat_id, usuario.email, texto)

    pendiente = pendientes.mirar(chat_id)

    # La confirmación de un audio va antes que el resto: lo que se contesta acá
    # no es la pregunta de un movimiento a medio anotar, es si el bot escuchó
    # bien. Si el usuario confirma, seguimos con ese texto como si lo hubiera
    # escrito él.
    if pendiente is not None and pendiente.tipo == "confirmar_audio":
        texto = await _resolver_confirmacion_audio(chat_id, pendiente, texto)
        if texto is None:
            return
        pendiente = None

    if pendiente is not None:
        try:
            respuesta = await _resolver_pendiente(
                chat_id, pendiente, texto, usuario.user_id
            )
        except Exception:
            logger.exception("Error resolviendo la pregunta pendiente de %s", chat_id)
            pendientes.olvidar(chat_id)
            await _responder(chat_id, MSG_ERROR_INTERNO)
            return

        if respuesta is not None:
            await _responder(chat_id, respuesta)
            return

        logger.info("El mensaje no contestaba la pregunta abierta; se descarta")
        pendientes.olvidar(chat_id)

    directa = respuesta_directa(texto)
    if directa is not None:
        logger.info("Respuesta fija para %r", texto)
        await _responder(chat_id, directa)
        return

    if _es_comando_reto(texto):
        logger.info("Comando de reto de %s: %r", chat_id, texto)
        await _responder(
            chat_id,
            await run_in_threadpool(_atender_reto, chat_id, texto, usuario.user_id),
        )
        return

    if _es_comando_recurrentes(texto):
        logger.info("Comando de recurrentes de %s", chat_id)
        await _responder(
            chat_id, await run_in_threadpool(_texto_recurrentes, usuario.user_id)
        )
        return

    if _es_comando_rendimientos(texto):
        logger.info("Comando de rendimientos de %s", chat_id)
        await _responder(chat_id, await run_in_threadpool(_texto_rendimientos))
        return

    if es_comando_recordatorio(texto):
        logger.info("Comando de recordatorio de %s: %r", chat_id, texto)
        respuesta = await run_in_threadpool(
            atender_comando_recordatorio, chat_id, texto, usuario.user_id
        )
        await _responder(chat_id, respuesta)
        return

    try:
        vocabulario = await run_in_threadpool(_vocabulario, usuario.user_id)
    except Exception:
        # Un vocabulario vacío no frena al bot: el parser vuelve a aceptar lo
        # que diga el modelo, como antes de que existieran las categorías. Pasa
        # si todavía no se corrió migrations/019_categorias.sql, y Render se
        # despliega solo apenas hay push.
        logger.exception(
            "No pude leer las categorías de %s: sigo sin lista. ¿Falta correr "
            "migrations/019_categorias.sql?", chat_id,
        )
        vocabulario = Vocabulario([])

    # "¿qué categorías tengo?" y "creá la categoría X" no tienen nada que
    # interpretar, y el cupo de Gemini es de 20 por hora: se resuelven acá.
    comando = leer_comando_categorias(texto)
    if comando is not None:
        logger.info("Comando de categorías de %s: %r", chat_id, texto)
        try:
            respuesta = await _resolver_gestion_categorias(
                GestionCategoria(
                    accion=AccionCategoria(comando.accion), nombre=comando.nombre
                ),
                vocabulario,
                chat_id,
                usuario.user_id,
            )
        except Exception:
            logger.exception("Error gestionando las categorías de %s", chat_id)
            await _responder(chat_id, MSG_ERROR_INTERNO)
            return
        await _responder(chat_id, respuesta)
        return

    try:
        interpretacion = await run_in_threadpool(
            interpretar_mensaje, texto, vocabulario
        )
    except ServicioNoDisponible as exc:
        logger.error("Gemini no está disponible para %s: %s", chat_id, exc)
        await _responder(chat_id, MSG_SERVICIO_CAIDO)
        return
    except ParserError as exc:
        logger.info("No se pudo interpretar %r: %s", texto, exc)
        await _responder(chat_id, MSG_NO_ENTENDI)
        return
    except Exception:
        logger.exception("Error inesperado interpretando %r", texto)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    try:
        respuesta = await _resolver(
            interpretacion, chat_id, usuario.user_id, vocabulario
        )
    except Exception:
        logger.exception("Error resolviendo la intención %s", interpretacion.intencion)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    await _responder(chat_id, respuesta)


MSG_POR_PROBLEMA = {
    Problema.VACIO: MSG_AUDIO_VACIO,
    Problema.INAUDIBLE: MSG_AUDIO_INAUDIBLE,
    Problema.NO_ES_PLATA: MSG_AUDIO_NO_ES_PLATA,
}

_CONFIRMAN = frozenset({
    "si", "sí", "sisi", "si si", "sip", "dale", "ok", "oka", "okey", "okay",
    "correcto", "exacto", "eso", "eso es", "tal cual", "asi es", "así es",
    "obvio", "perfecto", "confirmo", "anotalo", "anotá", "anota", "listo",
    "👍", "👌", "✅",
})

_RECHAZAN = frozenset({
    "no", "nop", "nope", "negativo", "cancelar", "cancela", "cancelalo",
    "dejalo", "dejá", "deja", "olvidalo", "nada", "mal", "no era", "no es",
    "borralo", "❌",
})


def _leer_confirmacion(texto: str) -> bool | None:
    """True si confirmó, False si rechazó, None si contestó otra cosa.

    Esa tercera opción no es un caso raro: lo natural cuando el bot entendió
    mal es reescribir el mensaje, no decir «no». Quien llama trata ese texto
    como el mensaje bueno.
    """
    limpio = " ".join((texto or "").split()).strip().lower()
    limpio = limpio.strip(".,;:!¡?¿ ")

    if limpio in _CONFIRMAN:
        return True
    if limpio in _RECHAZAN:
        return False
    return None


def _texto_confirmacion(transcripcion: Transcripcion) -> str:
    """Le repite al usuario lo que se entendió, antes de anotar nada."""
    if transcripcion.dudas:
        flojo = transcripcion.dudas[0]
        if len(transcripcion.dudas) > 1:
            flojo = " ni ".join(transcripcion.dudas[:2])
        aclaracion = f"No me quedó claro {flojo}."
    else:
        aclaracion = "No estoy del todo seguro de haber escuchado bien."

    return (
        f"Entendí: «{transcripcion.texto}»\n"
        f"{aclaracion}\n\n"
        "¿Lo anoto así? Decime «sí», o escribime cómo era."
    )


async def _escuchar_audio(chat_id: int, voz: VozEntrante) -> str | None:
    """Convierte un audio en el texto que el usuario habría escrito.

    Devuelve None cuando ya se le contestó al usuario: puede ser un error, o
    puede ser que el audio quedó dudoso y se abrió una pregunta para
    confirmarlo. Anotar un movimiento con un monto adivinado es peor que
    volver a preguntar, así que ante la duda no se devuelve texto.
    """
    if voz.duracion > TOPE_AUDIO_SEGUNDOS:
        logger.info("Audio de %s descartado: dura %ss", chat_id, voz.duracion)
        await _responder(chat_id, MSG_AUDIO_LARGO)
        return None

    if voz.tamano > TOPE_AUDIO_BYTES:
        logger.info("Audio de %s descartado: pesa %s bytes", chat_id, voz.tamano)
        await _responder(chat_id, MSG_AUDIO_PESADO)
        return None

    try:
        LIMITE_AUDIO.revisar(str(chat_id))
    except LimiteExcedido:
        logger.warning("Cupo de audios agotado por el chat %s", chat_id)
        await _responder(chat_id, MSG_MUCHOS_AUDIOS)
        return None

    try:
        audio = await descargar_archivo(voz.file_id, TOPE_AUDIO_BYTES)
    except ArchivoDemasiadoGrande:
        logger.info("Audio de %s más grande de lo que bajo", chat_id)
        await _responder(chat_id, MSG_AUDIO_PESADO)
        return None
    except TelegramError:
        logger.exception("No pude bajar el audio de %s", chat_id)
        await _responder(chat_id, MSG_AUDIO_FALLO)
        return None

    try:
        transcripcion = await run_in_threadpool(
            transcribir_audio, audio, voz.mime, voz.duracion
        )
    except AudioMuyLargo:
        await _responder(chat_id, MSG_AUDIO_LARGO)
        return None
    except ServicioNoDisponible as exc:
        logger.error("Gemini no está para transcribir el audio de %s: %s", chat_id, exc)
        await _responder(chat_id, MSG_SERVICIO_CAIDO)
        return None
    except ParserError as exc:
        logger.info("No pude transcribir el audio de %s: %s", chat_id, exc)
        await _responder(chat_id, MSG_AUDIO_INAUDIBLE)
        return None
    except Exception:
        logger.exception("Error inesperado transcribiendo el audio de %s", chat_id)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return None

    if transcripcion.problema is not None:
        logger.info(
            "Audio de %s sin nada que anotar: %s", chat_id, transcripcion.problema.value
        )
        await _responder(chat_id, MSG_POR_PROBLEMA[transcripcion.problema])
        return None

    logger.info(
        "Audio de %s (%ss, confianza %s): %r",
        chat_id, voz.duracion, transcripcion.confianza.value, transcripcion.texto,
    )

    if not transcripcion.hay_que_confirmar:
        await _responder(chat_id, MSG_ESCUCHE.format(texto=transcripcion.texto))
        return transcripcion.texto

    pendientes.guardar(
        chat_id,
        pendientes.Pendiente(
            tipo="confirmar_audio", datos={"texto": transcripcion.texto}
        ),
    )
    await _responder(chat_id, _texto_confirmacion(transcripcion))
    return None


async def _resolver_confirmacion_audio(
    chat_id: int, pendiente, texto: str
) -> str | None:
    """Qué texto procesar después de que el usuario contestó la confirmación.

    None significa que no hay nada más que hacer: ya se le respondió.
    """
    pendientes.olvidar(chat_id)
    decision = _leer_confirmacion(texto)

    if decision is False:
        logger.info("El chat %s descartó lo que entendí del audio", chat_id)
        await _responder(chat_id, MSG_AUDIO_CANCELADO)
        return None

    if decision is None:
        # Reescribió el mensaje en vez de contestar sí o no: eso es lo que vale.
        logger.info("El chat %s corrigió a mano lo que entendí del audio", chat_id)
        return texto

    confirmado = (pendiente.datos or {}).get("texto") or ""
    if not confirmado.strip():
        logger.warning("Confirmación de audio sin texto guardado en %s", chat_id)
        await _responder(chat_id, MSG_AUDIO_VACIO)
        return None

    logger.info("El chat %s confirmó el audio: %r", chat_id, confirmado)
    return confirmado


async def _autorizar(chat_id: int) -> Usuario | None:
    """El usuario dueño del chat, o None si el mensaje no se procesa."""
    usuario = await run_in_threadpool(resolver_usuario, chat_id)

    if usuario is not None and usuario.habilitado:
        if CHATS_PERMITIDOS and chat_id not in CHATS_PERMITIDOS:
            logger.warning(
                "Chat %s habilitado en la base pero fuera de CHATS_PERMITIDOS", chat_id
            )
        else:
            return usuario

    await _avisar_sin_acceso(chat_id)
    return None


async def _avisar_sin_acceso(chat_id: int) -> None:
    """Le dice al chat que no tiene acceso, como mucho una vez cada media hora."""
    ahora = time.monotonic()
    ultimo = _ultimo_aviso.get(chat_id)
    if ultimo is not None and ahora - ultimo < ESPERA_SIN_ACCESO:
        logger.info("Chat %s sin acceso (aviso ya mandado, no repito)", chat_id)
        return

    if len(_ultimo_aviso) >= TOPE_AVISOS:
        _podar_avisos(ahora)

    _ultimo_aviso[chat_id] = ahora
    logger.warning("Chat %s sin acceso: le aviso", chat_id)
    await _responder(chat_id, MSG_SIN_ACCESO.format(chat_id=chat_id))


def _podar_avisos(ahora: float) -> None:
    """Saca los avisos ya vencidos y, si sigue lleno, los más viejos."""
    for chat, cuando in list(_ultimo_aviso.items()):
        if ahora - cuando >= ESPERA_SIN_ACCESO:
            del _ultimo_aviso[chat]

    if len(_ultimo_aviso) >= TOPE_AVISOS:
        viejos = sorted(_ultimo_aviso, key=_ultimo_aviso.get)
        for chat in viejos[: len(_ultimo_aviso) - TOPE_AVISOS + 1]:
            del _ultimo_aviso[chat]


async def _resolver(
    interpretacion: Interpretacion,
    chat_id: int,
    user_id: str,
    vocabulario: Vocabulario,
) -> str:
    """Ejecuta la intención y devuelve el texto a mandarle al usuario."""
    intencion = interpretacion.intencion

    if intencion is Intencion.REGISTRAR:
        movimiento = await run_in_threadpool(
            _con_clave_item, interpretacion.movimiento, user_id
        )
        if interpretacion.objetivo:
            # El objetivo también abre una pregunta, y solo hay una por chat.
            # Gana esa: dónde va la plata importa más que con qué etiqueta
            # quedó, y el movimiento igual entra en "otros".
            return await _registrar_hacia_objetivo(
                chat_id, movimiento, interpretacion.objetivo, user_id
            )

        aviso = await run_in_threadpool(_aviso_de_salto, movimiento, user_id)
        aviso_reto = await run_in_threadpool(_aviso_de_reto, movimiento, chat_id, user_id)
        movimiento_id = await run_in_threadpool(
            guardar_movimiento, movimiento, user_id=user_id
        )
        logger.info("Movimiento %s guardado: %s", movimiento_id, movimiento)

        pregunta = ""
        if interpretacion.categoria_nueva:
            pregunta = await _abrir_preguntas_categoria(
                chat_id,
                [(movimiento_id, interpretacion.categoria_nueva, movimiento.tipo)],
                vocabulario,
                user_id,
                movimiento.moneda,
            )

        return _confirmacion(movimiento) + aviso + aviso_reto + pregunta

    if intencion is Intencion.REGISTRAR_VARIOS:
        return await _resolver_varios(interpretacion, chat_id, user_id, vocabulario)

    if intencion is Intencion.GESTIONAR_CATEGORIAS:
        return await _resolver_gestion_categorias(
            interpretacion.gestion, vocabulario, chat_id, user_id
        )

    if intencion is Intencion.REGISTRAR_INVERSION:
        return await _resolver_inversion(interpretacion, user_id)

    if intencion is Intencion.REGISTRAR_INVERSIONES:
        return await _resolver_inversiones(interpretacion, user_id)

    if intencion is Intencion.CERRAR_INVERSION:
        return await _resolver_cierre(interpretacion, user_id)

    if intencion is Intencion.CREAR_ALERTA:
        return await _resolver_alerta(interpretacion, chat_id, user_id)

    if intencion is Intencion.VER_ALERTAS:
        return await _texto_alertas(chat_id, user_id)

    if intencion is Intencion.SIMULAR_COMPRA:
        return await run_in_threadpool(_resolver_compra, interpretacion.compra, user_id)

    if intencion is Intencion.COMPARAR_CUOTAS:
        return await _resolver_cuotas(
            interpretacion.financiacion, interpretacion.faltantes, user_id
        )

    if intencion is Intencion.CONSULTA_LIBRE:
        return await run_in_threadpool(_resolver_plan, interpretacion.plan, user_id)

    if intencion is Intencion.DESCONOCIDA or interpretacion.consulta is None:
        return MSG_NO_ENTENDI

    consulta = interpretacion.consulta
    logger.info("Consulta %s: %s", intencion.value, consulta)

    if intencion is Intencion.TOTAL_POR_TIPO:
        return await run_in_threadpool(_texto_total_por_tipo, consulta, user_id)
    if intencion is Intencion.TOTAL_POR_CATEGORIA:
        return await run_in_threadpool(_texto_por_categoria, consulta, user_id)
    if intencion is Intencion.BALANCE:
        return await run_in_threadpool(_texto_balance, consulta, user_id)

    return MSG_NO_ENTENDI


async def _resolver_alerta(
    interpretacion: Interpretacion, chat_id: int, user_id: str
) -> str:
    """Crea la alerta, o pregunta lo que falte."""
    if interpretacion.faltantes or not interpretacion.alerta:
        return _pedir_faltantes_alerta(interpretacion.faltantes)

    alerta = interpretacion.alerta

    referencia = None
    moneda = None
    try:
        datos = await precio_de_mercado(alerta.ticker, alerta.mercado)
        referencia = Decimal(str(datos["precio"]))
        moneda = datos.get("moneda")
    except MercadoError as exc:
        if alerta.tipo in (TipoAlerta.BAJA, TipoAlerta.SUBE):
            return (
                f"No pude traer el precio de {alerta.ticker} para tomarlo de "
                f"referencia, así que no puedo medir una variación desde hoy.\n\n"
                f"{exc}\n\n"
                f"Probá con un precio concreto: «avisame si {alerta.ticker} baja de 100»."
            )
        logger.info("Alerta sobre %s sin precio de referencia: %s", alerta.ticker, exc)

    fila = await run_in_threadpool(
        crear_alerta,
        alerta,
        user_id=user_id,
        chat_id=chat_id,
        referencia=referencia,
        moneda=moneda,
    )
    logger.info("Alerta %s creada para %s", fila.get("id"), alerta.ticker)
    return _confirmacion_alerta(alerta, referencia, moneda)


def _pedir_faltantes_alerta(faltantes: tuple[str, ...]) -> str:
    etiquetas = {
        "ticker": "qué activo querés vigilar",
        "umbral": "de cuánto es el umbral",
        "tipo": "si querés que te avise cuando suba o cuando baje",
    }
    pedidos = [etiquetas.get(f, f) for f in faltantes] or ["algún dato"]
    detalle = pedidos[0] if len(pedidos) == 1 else ", ".join(pedidos[:-1]) + f" y {pedidos[-1]}"

    return (
        f"Me falta saber {detalle}.\n\n"
        "Probá algo como:\n"
        "«avisame si AAPL baja 5%»\n"
        "«avisame si TSLA supera los 300 dólares»"
    )


def _confirmacion_alerta(alerta: Alerta, referencia: Decimal | None, moneda: str | None) -> str:
    donde = "en BYMA" if alerta.mercado == "ar" else ""
    umbral = _formatear_cantidad(alerta.umbral)

    if alerta.tipo in (TipoAlerta.BAJA, TipoAlerta.SUBE):
        verbo = "baja" if alerta.tipo is TipoAlerta.BAJA else "sube"
        desde = f" desde {_formatear_monto(referencia, Moneda(moneda))}" if referencia and moneda else ""
        return (
            f"🔔 Listo. Te aviso si {alerta.ticker} {donde} {verbo} {umbral}%{desde}.\n\n"
            "Cuando suene se apaga sola, para no repetirse."
        ).replace("  ", " ")

    direccion = "baja de" if alerta.tipo is TipoAlerta.DEBAJO else "supera"
    precio = _formatear_monto(alerta.umbral, Moneda(moneda)) if moneda else umbral
    return (
        f"🔔 Listo. Te aviso si {alerta.ticker} {donde} {direccion} {precio}.\n\n"
        "Cuando suene se apaga sola, para no repetirse."
    ).replace("  ", " ")


async def _texto_alertas(chat_id: int, user_id: str) -> str:
    """Las alertas activas de este chat."""
    filas = await run_in_threadpool(alertas_de_chat, chat_id, user_id=user_id)
    if not filas:
        return (
            "No tenés alertas activas.\n\n"
            "Podés pedirme una así: «avisame si AAPL baja 5%»."
        )

    lineas = ["🔔 Tus alertas activas:", ""]
    for f in filas:
        umbral = _formatear_cantidad(Decimal(str(f["umbral"])))
        if f["tipo"] in ("baja", "sube"):
            que = f"{'baja' if f['tipo'] == 'baja' else 'sube'} {umbral}%"
        else:
            que = f"{'baja de' if f['tipo'] == 'debajo' else 'supera'} {umbral}"
        lineas.append(f"• {f['ticker']} — si {que}")

    return "\n".join(lineas)


async def _resolver_cuotas(
    financiacion: Financiacion | None, faltantes: tuple[str, ...], user_id: str
) -> str:
    """Compara cuotas contra contado. No registra nada: todavía no compró."""
    if financiacion is None:
        return pedir_faltantes_cuotas(faltantes or ("cuotas", "monto_cuota", "precio_contado"))

    logger.info(
        "Cuotas vs contado: %s x %s vs %s",
        financiacion.cuotas, financiacion.monto_cuota, financiacion.precio_contado,
    )

    tasas = await run_in_threadpool(obtener_tasas)
    comparacion = comparar_cuotas(financiacion, tasas)

    try:
        tiene_inversiones = bool(
            await run_in_threadpool(obtener_inversiones, user_id=user_id, limite=1)
        )
    except Exception:
        logger.warning("No pude ver si tiene inversiones", exc_info=True)
        tiene_inversiones = False

    cartera = None
    if tiene_inversiones and financiacion.tasa_mensual is None:
        try:
            cartera = await rendimiento_cartera(financiacion.moneda, user_id=user_id)
        except Exception:
            logger.warning("No pude calcular el rendimiento de la cartera", exc_info=True)

    return redactar_cuotas(comparacion, _formatear_monto, tiene_inversiones, cartera)


def _resolver_compra(compra: CompraHipotetica | None, user_id: str) -> str:
    """Analiza una compra hipotética. NO la registra: no pasó todavía."""
    if compra is None:
        return MSG_NO_ENTENDI

    logger.info("Compra hipotética: %s %s (%s)", compra.monto, compra.moneda.value, compra.que)
    return redactar_analisis(analizar_compra(compra, user_id=user_id), _formatear_monto)


def _resolver_plan(plan: PlanConsulta | None, user_id: str) -> str:
    """Ejecuta una pregunta analítica libre y devuelve la respuesta redactada."""
    if plan is None:
        return MSG_NO_ENTENDI

    logger.info("Consulta libre: %s", plan.model_dump(exclude_defaults=True))

    resultado = ejecutar_plan(plan, user_id=user_id)
    comparacion = (
        ejecutar_plan(plan, plan.comparar_con, user_id=user_id)
        if plan.comparar_con
        else None
    )
    return redactar_plan(plan, resultado, _formatear_monto, comparacion)


_COMANDOS_RETO = frozenset({"/reto", "/retos", "/desafio", "/acepto"})


def _es_comando_reto(texto: str) -> bool:
    return (texto or "").strip().lower().split("@", 1)[0] in _COMANDOS_RETO


def _atender_reto(chat_id: int, texto: str, user_id: str) -> str:
    """Propone, acepta o informa el reto. Todo en un comando por simplicidad."""
    comando = texto.strip().lower().split("@", 1)[0]

    abierto = reto_activo(chat_id, user_id=user_id)
    if abierto:
        gastado = gastado_en_reto(abierto, user_id=user_id)
        nuevo = revisar_reto(abierto, gastado)
        if nuevo:
            cerrar_reto(abierto["id"], nuevo, gastado)
            if nuevo == "cumplido":
                return texto_cumplido(abierto, _formatear_monto, Moneda(abierto.get("moneda", "ARS")))
            return texto_fallido(abierto, gastado, _formatear_monto, Moneda(abierto.get("moneda", "ARS")))
        return texto_activo(abierto, gastado, _formatear_monto, Moneda(abierto.get("moneda", "ARS")))

    filas = movimientos_para_termometro(user_id=user_id)
    conteo: dict[str, int] = {}
    for fila in filas:
        conteo[fila.get("moneda", "ARS")] = conteo.get(fila.get("moneda", "ARS"), 0) + 1
    moneda = Moneda(max(conteo, key=conteo.get)) if conteo else Moneda.ARS

    propuesta = proponer_reto(filas, moneda.value)
    if propuesta is None:
        return texto_sin_propuesta()

    if comando != "/acepto":
        return texto_propuesta(propuesta, _formatear_monto, moneda)

    hoy = date.today()
    try:
        reto = crear_reto(
            chat_id,
            user_id=user_id,
            categoria=propuesta.categoria,
            ahorro_estimado=propuesta.ahorro_estimado,
            moneda=moneda.value,
            desde=hoy,
            hasta=hoy + timedelta(days=DURACION_RETO),
        )
    except DBError as exc:
        logger.error("No pude crear el reto: %s", exc)
        return "No pude arrancar el reto 😬 Probá de nuevo en un ratito."

    return texto_aceptado(reto, _formatear_monto, moneda)


def _aviso_de_reto(movimiento: Movimiento, chat_id: int, user_id: str) -> str:
    """Si el gasto rompe un reto activo, se dice al confirmarlo."""
    if movimiento.tipo is not TipoMovimiento.GASTO:
        return ""

    abierto = reto_activo(chat_id, user_id=user_id)
    if not abierto or abierto.get("categoria") != movimiento.categoria:
        return ""

    gastado = gastado_en_reto(abierto, user_id=user_id) + movimiento.monto
    nuevo = revisar_reto(abierto, gastado)
    if nuevo != "fallido":
        return ""

    cerrar_reto(abierto["id"], "fallido", gastado)
    return f"\n\n💔 Ahí se cortó el reto de {abierto['categoria']}. Si querés otro: /reto"


_COMANDOS_RECURRENTES = frozenset({
    "/recurrentes", "/suscripciones", "/subs",
})


def _es_comando_recurrentes(texto: str) -> bool:
    clave = (texto or "").strip().lower().split("@", 1)[0]
    return clave in _COMANDOS_RECURRENTES


def _texto_recurrentes(user_id: str) -> str:
    """Los cargos que se repiten, con la sugerencia de revisarlos."""
    try:
        filas = movimientos_para_termometro(user_id=user_id)
    except Exception:
        logger.exception("No pude leer los movimientos para recurrentes")
        return MSG_ERROR_INTERNO

    conteo: dict[str, int] = {}
    for fila in filas:
        conteo[fila.get("moneda", "ARS")] = conteo.get(fila.get("moneda", "ARS"), 0) + 1
    moneda = Moneda(max(conteo, key=conteo.get)) if conteo else Moneda.ARS

    encontrados = detectar_recurrentes(filas, moneda.value)
    logger.info("Recurrentes detectados: %s en %s", len(encontrados), moneda.value)
    return redactar_recurrentes(encontrados, moneda, _formatear_monto)


_COMANDOS_RENDIMIENTOS = frozenset({
    "/rendimientos", "/billeteras", "/tasas",
})

TOPE_RENDIMIENTOS = 10


def _es_comando_rendimientos(texto: str) -> bool:
    clave = (texto or "").strip().lower().split("@", 1)[0]
    return clave in _COMANDOS_RENDIMIENTOS


def _texto_rendimientos() -> str:
    """El ranking de billeteras por TNA, con la fecha del dato bien visible."""
    filas = obtener_rendimientos(limite=TOPE_RENDIMIENTOS)

    if not filas:
        return (
            "Todavía no tengo tasas de billeteras cargadas 🤷\n\n"
            "Las actualiza un proceso automático una vez por día. Si recién "
            "arrancaste, esperá a la próxima corrida."
        )

    fechas = [f["fecha_actualizacion"] for f in filas if f.get("fecha_actualizacion")]
    mas_vieja = min(fechas) if fechas else None

    lineas = ["💰 Rendimientos de billeteras\n"]

    for puesto, fila in enumerate(filas, start=1):
        try:
            tna = Decimal(str(fila["tna"]))
        except (KeyError, ValueError, ArithmeticError):
            continue

        tna_txt = f"{tna:.2f}".replace(".", ",")
        mensual = f"{tna / 12:.2f}".replace(".", ",")

        medalla = {1: "🥇", 2: "🥈", 3: "🥉"}.get(puesto, "  ")
        linea = f"{medalla} {fila['nombre']} — {tna_txt}% TNA ({mensual}% mensual)"

        tope = fila.get("tope_monto")
        if tope:
            try:
                linea += f"\n     hasta {_formatear_monto(Decimal(str(tope)), Moneda.ARS)}"
            except (ValueError, ArithmeticError):
                pass

        lineas.append(linea)

    if mas_vieja:
        try:
            dia = date.fromisoformat(mas_vieja)
            lineas.append(f"\n📅 Tasas al {dia.strftime('%d/%m/%Y')}")
            atraso = (date.today() - dia).days
            if atraso > 7:
                lineas.append(
                    f"⚠️ Hace {atraso} días que no se actualizan. "
                    "Puede que la fuente esté caída: verificá antes de mover plata."
                )
        except ValueError:
            pass

    lineas.append(
        "\nSon rendimientos variables y no garantizados. La mayoría sale de un "
        "fondo común de dinero, así que la tasa cambia todos los días."
    )
    return "\n".join(lineas)


def _con_clave_item(movimiento: Movimiento | None, user_id: str) -> Movimiento | None:
    """Le agrega al movimiento la clave con la que se agrupa su ítem."""
    if movimiento is None or movimiento.tipo is not TipoMovimiento.GASTO:
        return movimiento

    try:
        clave = clave_para(
            descripcion=movimiento.descripcion,
            comercio=movimiento.comercio,
            conocidas=claves_de_items(user_id=user_id),
        )
    except Exception:
        logger.warning("No pude calcular la clave del ítem", exc_info=True)
        return movimiento

    return movimiento.model_copy(update={"clave_item": clave or None})


def _aviso_de_salto(movimiento: Movimiento, user_id: str) -> str:
    """La línea extra cuando el ítem se despegó de lo que venía saliendo."""
    if movimiento.clave_item is None or movimiento.tipo is not TipoMovimiento.GASTO:
        return ""

    try:
        historial = historial_de_item(movimiento.clave_item, user_id=user_id)
    except Exception:
        logger.warning("No pude revisar el historial del ítem", exc_info=True)
        return ""

    usa_unitario = movimiento.precio_unitario is not None
    nuevo = movimiento.precio_unitario if usa_unitario else movimiento.monto

    previos = []
    for fila in historial:
        if fila.get("moneda") != movimiento.moneda.value:
            continue
        crudo = fila.get("precio_unitario") if usa_unitario else fila.get("monto")
        if crudo is None:
            continue
        try:
            valor = Decimal(str(crudo))
        except (InvalidOperation, ValueError):
            continue
        if valor > 0:
            previos.append(valor)

    salto = detectar_salto(nuevo, previos)
    if salto is None:
        return ""

    ordenados = sorted(previos)
    medio = len(ordenados) // 2
    habitual = (
        ordenados[medio] if len(ordenados) % 2
        else (ordenados[medio - 1] + ordenados[medio]) / 2
    )
    unidad = f" por {movimiento.unidad}" if usa_unitario and movimiento.unidad else ""
    verbo = "más" if salto > 0 else "menos"
    flecha = "📈" if salto > 0 else "📉"

    return (
        f"\n{flecha} Ojo: {movimiento.clave_item} venía saliendo "
        f"~{_formatear_monto(habitual.quantize(Decimal('0.01')), movimiento.moneda)}{unidad}. "
        f"Esto es {abs(salto) * 100:.0f}% {verbo}."
    )


async def _resolver_varios(
    interpretacion: Interpretacion,
    chat_id: int,
    user_id: str,
    vocabulario: Vocabulario,
) -> str:
    """Guarda los movimientos que vinieron completos y pregunta por el resto."""
    movimientos = list(interpretacion.movimientos)
    dudas = interpretacion.dudas

    if not movimientos:
        return _texto_dudas(dudas, ninguno_guardado=True)

    ids = await run_in_threadpool(guardar_movimientos, movimientos, user_id=user_id)
    logger.info("Movimientos guardados en lote: %s", ids)

    # El parser devuelve la POSICIÓN de cada ítem sin categoría, porque el id
    # recién existe después de guardar. Acá se cruzan las dos listas.
    faltantes = [
        (ids[posicion], mencion, movimientos[posicion].tipo)
        for posicion, mencion in interpretacion.sin_categoria
        if posicion < len(ids)
    ]

    pregunta = await _abrir_preguntas_categoria(
        chat_id, faltantes, vocabulario, user_id, movimientos[0].moneda
    )

    return _texto_resumen(movimientos, dudas) + pregunta


def _texto_resumen(
    movimientos: list[Movimiento], dudas: tuple[tuple[str, str], ...]
) -> str:
    """Ej: '✅ Registré 3 gastos por $37.000' + el detalle + lo que quedó en duda."""
    por_clave: dict[tuple[str, Moneda], Decimal] = {}
    cuantos: dict[tuple[str, Moneda], int] = {}
    for m in movimientos:
        clave = (m.tipo.value, m.moneda)
        por_clave[clave] = por_clave.get(clave, Decimal("0")) + m.monto
        cuantos[clave] = cuantos.get(clave, 0) + 1

    encabezados = []
    for (tipo, moneda), total in sorted(por_clave.items(), key=lambda kv: kv[0][0]):
        cantidad = cuantos[(tipo, moneda)]
        etiqueta = _ETIQUETA_TIPO[tipo][2 if cantidad > 1 else 0].lower()
        encabezados.append(
            f"{cantidad} {etiqueta} por {_formatear_monto(total, moneda)}"
        )

    lineas = [f"✅ Registré {' · '.join(encabezados)}"]
    lineas += [
        f"  • {m.descripcion or m.categoria}: "
        f"{_formatear_monto(m.monto, m.moneda)} ({m.categoria})"
        for m in movimientos
    ]

    if dudas:
        lineas.append("")
        lineas.append(_texto_dudas(dudas))

    return "\n".join(lineas)


def _texto_dudas(dudas: tuple[tuple[str, str], ...], ninguno_guardado: bool = False) -> str:
    """Pregunta solo por los ítems que quedaron sin resolver, citándolos."""
    if not dudas:
        return MSG_NO_ENTENDI

    cabeza = (
        "No pude anotar nada de eso 🤔"
        if ninguno_guardado
        else ("Me quedó una duda:" if len(dudas) == 1 else "Me quedaron dudas:")
    )
    cuerpo = [f"❓ «{cita}» — {pregunta}" for cita, pregunta in dudas]
    pie = "Contestame solo eso y lo agrego." if not ninguno_guardado else ""

    return "\n".join([cabeza, *cuerpo] + ([pie] if pie else []))


async def _resolver_inversion(interpretacion: Interpretacion, user_id: str) -> str:
    """Guarda la compra, o pregunta por lo que falte en vez de inventarlo."""
    if interpretacion.faltantes:
        return _pedir_faltantes(interpretacion.faltantes)

    inversion = interpretacion.inversion
    inversion_id = await run_in_threadpool(
        guardar_inversion, inversion, user_id=user_id
    )
    logger.info("Inversión %s guardada: %s", inversion_id, inversion)
    return _confirmacion_inversion(inversion)


async def _resolver_inversiones(interpretacion: Interpretacion, user_id: str) -> str:
    """Guarda las compras completas y avisa cuáles quedaron sin datos."""
    compras = list(interpretacion.inversiones)
    incompletas = interpretacion.faltantes

    if not compras:
        return _texto_incompletas(incompletas)

    ids = await run_in_threadpool(guardar_inversiones, compras, user_id=user_id)
    logger.info("Inversiones guardadas en lote: %s", ids)

    lineas = []
    for inv in compras:
        identidad = f"{inv.ticker} ({inv.nombre})" if inv.ticker else inv.nombre
        total = inv.cantidad * inv.precio_compra
        lineas.append(
            f"· {_formatear_cantidad(inv.cantidad)} {identidad} — "
            f"{_formatear_monto(total, inv.moneda)}"
        )

    cabeza = f"{len(compras)} compras registradas" if len(compras) > 1 else "1 compra registrada"
    return "📈 " + cabeza + "\n" + "\n".join(lineas) + _texto_incompletas(incompletas, sufijo=True)


def _texto_incompletas(incompletas, sufijo: bool = False) -> str:
    """Lista las compras que no se pudieron guardar por falta de datos."""
    if not incompletas:
        return ""
    nombres = ", ".join(incompletas)
    aviso = (
        f"No pude guardar {nombres}: me falta la cantidad o el precio por unidad. "
        "Mandámelas de nuevo con los dos datos."
    )
    return ("\n\n" + aviso) if sufijo else aviso


async def _resolver_cierre(interpretacion: Interpretacion, user_id: str) -> str:
    """Cierra una tenencia vendida. No borra: la deja en el historial."""
    if interpretacion.faltantes:
        return _pedir_faltantes(interpretacion.faltantes)

    busqueda = interpretacion.cierre or ""
    try:
        cerradas = await run_in_threadpool(
            cerrar_inversiones, busqueda, user_id=user_id, fecha=interpretacion.cierre_fecha
        )
    except DBError as exc:
        logger.warning("No pude cerrar «%s»: %s", busqueda, exc)
        return f"No pude cerrar esa inversión. {exc}"

    if not cerradas:
        return (
            f"No encontré ninguna inversión abierta que coincida con «{busqueda}».\n\n"
            "Fijate el nombre exacto en la pantalla de Inversiones, o probá con el "
            "ticker: «vendí GGAL»."
        )

    return _confirmacion_cierre(cerradas, interpretacion.cierre_fecha)


def _confirmacion_cierre(cerradas: list[dict], fecha) -> str:
    """Ej: '📉 Posición cerrada · 13 GGAL (Galicia)'."""
    lineas = []
    for fila in cerradas:
        identidad = (
            f"{fila['ticker']} ({fila['nombre']})" if fila.get("ticker") else fila["nombre"]
        )
        lineas.append(f"{_formatear_cantidad(fila['cantidad'])} {identidad}")

    titulo = "📉 Posición cerrada" if len(cerradas) == 1 else f"📉 {len(cerradas)} posiciones cerradas"
    cuando = f" el {fecha:%d/%m}" if fecha else ""
    return (
        f"{titulo}{cuando}\n"
        + "\n".join(lineas)
        + "\n\nNo la borré: queda en el historial de la pantalla de Inversiones."
    )


def _pedir_faltantes(faltantes: tuple[str, ...]) -> str:
    """Pide los datos que faltan."""
    pedidos = [ETIQUETA_FALTANTE.get(campo, campo) for campo in faltantes]
    if len(pedidos) == 1:
        detalle = pedidos[0]
    else:
        detalle = ", ".join(pedidos[:-1]) + f" y {pedidos[-1]}"

    return (
        f"Me falta un dato para anotar esa compra: {detalle}.\n\n"
        "Mandámelo de nuevo completo, por ejemplo:\n"
        "«compré 10 CEDEARs de Apple a US$25»"
    )


def _confirmacion_inversion(inversion: Inversion) -> str:
    """Ej: '📈 Compra registrada\n0,5 BTC (Bitcoin) a US$60.000\nTotal: US$30.000'."""
    etiqueta = _ETIQUETA_INVERSION[inversion.tipo.value]
    total = inversion.cantidad * inversion.precio_compra
    identidad = (
        f"{inversion.ticker} ({inversion.nombre})" if inversion.ticker else inversion.nombre
    )

    if inversion.tipo is TipoInversion.PLAZO_FIJO and not inversion.precio_compra:
        return (
            f"📈 Compra registrada\n"
            f"{etiqueta} · {inversion.nombre}\n"
            f"Monto: {_formatear_monto(inversion.cantidad, inversion.moneda)} "
            f"({inversion.fecha_compra:%d/%m})"
        )

    return (
        f"📈 Compra registrada\n"
        f"{_formatear_cantidad(inversion.cantidad)} {identidad}\n"
        f"{etiqueta} · {_formatear_monto(inversion.precio_compra, inversion.moneda)} por unidad\n"
        f"Total: {_formatear_monto(total, inversion.moneda)} ({inversion.fecha_compra:%d/%m})"
    )


def _formatear_cantidad(cantidad: Decimal) -> str:
    """10 -> '10' · 0.5 -> '0,5' · 0.00010000 -> '0,0001' (sin ceros de relleno)."""
    normalizada = cantidad.normalize()
    if normalizada == normalizada.to_integral_value():
        return f"{int(normalizada):,}".replace(",", ".")
    return format(normalizada, "f").replace(".", ",")


async def _registrar_hacia_objetivo(
    chat_id: int, movimiento: Movimiento, mencion: str, user_id: str
) -> str:
    """Guarda el ahorro y, si puede, lo imputa. Si no, pregunta."""
    objetivos = await run_in_threadpool(obtener_objetivos, user_id=user_id)
    coincidencias = buscar(mencion, objetivos)

    if coincidencias.unico is not None:
        objetivo = coincidencias.unico
        movimiento_id = await run_in_threadpool(
            guardar_movimiento, movimiento, objetivo["id"], user_id=user_id
        )
        logger.info("Movimiento %s imputado a %r", movimiento_id, objetivo["nombre"])
        return await _texto_progreso(movimiento, objetivo, user_id)

    movimiento_id = await run_in_threadpool(
        guardar_movimiento, movimiento, user_id=user_id
    )
    logger.info("Movimiento %s guardado sin imputar (mención %r)", movimiento_id, mencion)

    if coincidencias.hay_varios:
        pendientes.guardar(
            chat_id,
            pendientes.Pendiente(
                tipo="elegir",
                movimiento_id=movimiento_id,
                mencion=mencion,
                moneda=movimiento.moneda.value,
                candidatos=coincidencias.objetivos,
            ),
        )
        lista = "\n".join(
            f"{i}. {o['nombre']}" for i, o in enumerate(coincidencias.objetivos, start=1)
        )
        return (
            f"{_confirmacion(movimiento)}\n\n"
            f"Tengo más de un objetivo que puede ser «{mencion}». ¿A cuál va?\n{lista}\n\n"
            "Contestame con el número, o «ninguno»."
        )

    pendientes.guardar(
        chat_id,
        pendientes.Pendiente(
            tipo="crear",
            movimiento_id=movimiento_id,
            mencion=mencion,
            moneda=movimiento.moneda.value,
        ),
    )
    return (
        f"{_confirmacion(movimiento)}\n\n"
        f"No tengo ningún objetivo que se llame «{mencion}». ¿Lo creo?\n"
        "Decime cuánto querés juntar (por ejemplo «500 mil») o «no» para dejarlo así."
    )


def _vocabulario(user_id: str) -> Vocabulario:
    """Las categorías que ese usuario puede usar, listas para el parser.

    Se lee en cada mensaje en vez de cachearse: importa más que la lista esté
    fresca justo después de crear una categoría que ahorrar una consulta.
    """
    filas = obtener_categorias(user_id=user_id)

    categorias = []
    for fila in filas:
        try:
            tipo = TipoMovimiento(fila["tipo"])
        except ValueError:
            logger.warning("Categoría con tipo desconocido: %r", fila.get("tipo"))
            continue
        categorias.append(
            Categoria(
                nombre=fila["nombre"],
                tipo=tipo,
                emoji=fila.get("emoji"),
                propia=fila.get("user_id") is not None,
            )
        )

    return Vocabulario(categorias)


# Respuestas que cierran la pregunta de categoría dejando el movimiento como
# está. "no" no significa lo mismo acá que en la pregunta de un objetivo, por
# eso la rama de categorías se resuelve antes.
_DEJARLO = frozenset(
    {
        "no", "dejalo", "dejala", "dejar", "otros", "esta bien", "asi esta bien",
        "ninguna", "ninguno", "nada", "cancelar", "no importa", "da igual",
    }
)

# Vacían la cola entera. Encadenar cuatro preguntas después de un cierre del día
# sin una salida sería insoportable.
_DEJAR_TODO = frozenset(
    {
        "dejalo todo", "deja todo", "dejalos", "dejalos en otros", "todo en otros",
        "deja todo en otros", "dejalo todo en otros", "basta", "listo", "despues",
        "despues veo", "ya fue",
    }
)


def _texto_pregunta_categoria(pendiente) -> str:
    """La pregunta por una categoría que no existe todavía."""
    opciones = "\n".join(
        f"  {i}. {c.get('emoji') or ''} {c['nombre']}".replace("  ", " ").rstrip()
        for i, c in enumerate(pendiente.candidatos, start=1)
    )

    cabeza = f"«{pendiente.mencion}» ¿dónde va?"
    if pendiente.restantes:
        cabeza += f"  (quedan {pendiente.restantes} después de esta)"

    pie = (
        f"Contestame con el número, «creá {pendiente.mencion}» para tener una "
        "categoría nueva, o «dejalo» para que quede en «otros»."
    )

    return "\n".join([cabeza, opciones, "", pie]) if opciones else f"{cabeza}\n{pie}"


async def _abrir_preguntas_categoria(
    chat_id: int,
    faltantes: list[tuple[int, str, TipoMovimiento]],
    vocabulario: Vocabulario,
    user_id: str,
    moneda: Moneda,
) -> str:
    """Deja abierta la pregunta por las categorías que no encajaron en ninguna.

    Los movimientos ya están guardados en «otros»: si el usuario no contesta, no
    se pierde nada. Lo que devuelve se pega debajo de la confirmación.
    """
    if not faltantes:
        return ""

    recortadas = faltantes[: pendientes.TOPE_COLA]

    # Las opciones que se ofrecen salen de lo que el usuario más usa. Se pide
    # una vez por tipo, no una por pregunta.
    frecuentes: dict[TipoMovimiento, tuple[str, ...]] = {}
    for _, _, tipo in recortadas:
        if tipo not in frecuentes:
            try:
                frecuentes[tipo] = await run_in_threadpool(
                    categorias_frecuentes, user_id=user_id, tipo=tipo
                )
            except Exception:
                logger.warning("No pude leer las categorías frecuentes", exc_info=True)
                frecuentes[tipo] = ()

    preguntas = [
        {
            "movimiento_id": movimiento_id,
            "mencion": mencion,
            "datos": {"tipo": tipo.value},
            "candidatos": [
                {"nombre": c.nombre, "emoji": c.emoji}
                for c in vocabulario.mas_cercanas(
                    mencion, tipo, frecuentes.get(tipo, ())
                )
            ],
        }
        for movimiento_id, mencion, tipo in recortadas
    ]

    primera = preguntas[0]
    pendiente = pendientes.Pendiente(
        tipo="categoria",
        movimiento_id=primera["movimiento_id"],
        mencion=primera["mencion"],
        moneda=moneda.value,
        candidatos=primera["candidatos"],
        cola=preguntas[1:],
        datos=primera["datos"],
    )
    pendientes.guardar(chat_id, pendiente)

    sobrantes = len(faltantes) - len(preguntas)
    aviso = (
        f"\n\n(Otros {sobrantes} quedaron en «otros», eran demasiados para "
        "preguntar de a uno.)"
        if sobrantes > 0
        else ""
    )

    return f"\n\n{_texto_pregunta_categoria(pendiente)}{aviso}"


async def _siguiente_pregunta(chat_id: int, pendiente, confirmacion: str) -> str:
    """Confirma lo que se hizo y pasa a la siguiente pregunta, si queda alguna."""
    if pendiente.avanzar():
        pendientes.guardar(chat_id, pendiente)
        return f"{confirmacion}\n\n{_texto_pregunta_categoria(pendiente)}"

    pendientes.olvidar(chat_id)
    return confirmacion


async def _resolver_pendiente_categoria(
    chat_id: int, pendiente, texto: str, user_id: str
) -> str | None:
    """Contesta a dónde iba el gasto, o None si el mensaje no contestaba eso."""
    clave = normalizar(texto)
    try:
        tipo = TipoMovimiento(pendiente.datos.get("tipo", "gasto"))
    except ValueError:
        tipo = TipoMovimiento.GASTO

    if clave in _DEJAR_TODO:
        pendientes.olvidar(chat_id)
        return "Listo, lo dejo todo en «otros» 👍"

    if clave in _DEJARLO:
        return await _siguiente_pregunta(
            chat_id, pendiente, f"Listo, «{pendiente.mencion}» queda en «otros» 👍"
        )

    elegido = _elegir_candidato(pendiente, clave)
    if elegido is not None:
        await run_in_threadpool(
            recategorizar_movimiento,
            pendiente.movimiento_id,
            elegido["nombre"],
            user_id=user_id,
        )
        etiqueta = f"{elegido.get('emoji') or ''} {elegido['nombre']}".strip()
        return await _siguiente_pregunta(chat_id, pendiente, f"Listo, va a {etiqueta} ✅")

    vocabulario = await run_in_threadpool(_vocabulario, user_id)

    # Crear exige el verbo ("creá cerámica"). Un nombre suelto solo se empareja
    # contra lo que ya existe: si no, cualquier mensaje que caiga mientras la
    # pregunta está abierta terminaría siendo una categoría.
    nueva = leer_creacion(texto, pendiente.mencion)
    if nueva is not None:
        ya_existe = vocabulario.resolver(nueva, tipo)
        if ya_existe is None:
            if len(vocabulario.propias()) >= TOPE_PROPIAS:
                return await _siguiente_pregunta(
                    chat_id,
                    pendiente,
                    f"Ya tenés {TOPE_PROPIAS} categorías propias, que son "
                    "bastantes 😅 Borrá alguna que no uses y volvé a intentar. "
                    f"«{pendiente.mencion}» queda en «otros» por ahora.",
                )
            try:
                await run_in_threadpool(
                    crear_categoria, user_id=user_id, nombre=nueva, tipo=tipo
                )
            except DBError as exc:
                logger.warning("No pude crear la categoría %r: %s", nueva, exc)
                return await _siguiente_pregunta(
                    chat_id,
                    pendiente,
                    f"No pude crear «{nueva}» 😕 Queda en «otros».",
                )
            confirmacion = f"Listo ✏️ Creé «{nueva}» y le puse ahí el movimiento."
        else:
            nueva = ya_existe.nombre
            confirmacion = f"Esa ya la tenías: lo puse en {ya_existe.etiqueta} ✅"

        await run_in_threadpool(
            recategorizar_movimiento, pendiente.movimiento_id, nueva, user_id=user_id
        )
        return await _siguiente_pregunta(chat_id, pendiente, confirmacion)

    encontrada = vocabulario.resolver(texto, tipo)
    if encontrada is not None:
        await run_in_threadpool(
            recategorizar_movimiento,
            pendiente.movimiento_id,
            encontrada.nombre,
            user_id=user_id,
        )
        return await _siguiente_pregunta(
            chat_id, pendiente, f"Listo, va a {encontrada.etiqueta} ✅"
        )

    return None


async def _resolver_pendiente_borrado(
    chat_id: int, pendiente, texto: str, user_id: str
) -> str | None:
    """Confirma el borrado de una categoría que tiene movimientos usándola."""
    clave = normalizar(texto)
    nombre = pendiente.mencion
    try:
        tipo = TipoMovimiento(pendiente.datos.get("tipo", "gasto"))
    except ValueError:
        tipo = TipoMovimiento.GASTO

    mover = clave in {
        "pasalos a otros", "pasalos", "pasalos todos", "moverlos", "movelos",
        "a otros", "pasar a otros", "mandalos a otros",
    }
    borrar = clave in {
        "borrala", "borralo", "borra", "borrar", "si", "dale", "sisi", "obvio",
        "borrala igual", "igual", "confirmo",
    }

    if clave in _DEJARLO or clave in _DEJAR_TODO:
        pendientes.olvidar(chat_id)
        return f"Listo, «{nombre}» se queda 👍"

    if not (mover or borrar):
        return None

    pendientes.olvidar(chat_id)
    movidos = 0

    try:
        if mover:
            movidos = await run_in_threadpool(
                recategorizar_todos,
                user_id=user_id,
                tipo=tipo,
                desde=nombre,
                hacia="otros",
            )
        await run_in_threadpool(
            borrar_categoria, user_id=user_id, nombre=nombre, tipo=tipo
        )
    except DBError as exc:
        logger.warning("No pude borrar la categoría %r: %s", nombre, exc)
        return f"No pude borrarla 😕\n{exc}"

    if movidos:
        return (
            f"Listo 🗑 Borré «{nombre}» y pasé {movidos} "
            f"{'movimiento' if movidos == 1 else 'movimientos'} a «otros»."
        )
    return (
        f"Listo 🗑 Borré «{nombre}». Los movimientos que ya la usaban quedan "
        "como están, así que tus gráficos no cambian."
    )


async def _resolver_gestion_categorias(
    gestion: GestionCategoria, vocabulario: Vocabulario, chat_id: int, user_id: str
) -> str:
    """Listar, crear o borrar categorías. Es lo único que las escribe."""
    if gestion.accion is AccionCategoria.LISTAR or not gestion.nombre:
        return formatear_listado(vocabulario)

    if gestion.accion is AccionCategoria.CREAR:
        return await _crear_categoria(gestion.nombre, gestion.tipo, vocabulario, user_id)

    return await _borrar_categoria(
        gestion.nombre, gestion.tipo, vocabulario, chat_id, user_id
    )


async def _crear_categoria(
    nombre: str, tipo: TipoMovimiento, vocabulario: Vocabulario, user_id: str
) -> str:
    """Da de alta una categoría propia, si no existía ya."""
    ya_existe = vocabulario.resolver(nombre, tipo)
    if ya_existe is not None:
        dueño = "tuya" if ya_existe.propia else "de las que vienen por defecto"
        return (
            f"Esa ya la tenés: {ya_existe.etiqueta} ({dueño}).\n"
            "Usala tranquilo, la voy a reconocer."
        )

    if len(vocabulario.propias()) >= TOPE_PROPIAS:
        return (
            f"Ya tenés {TOPE_PROPIAS} categorías propias, que son bastantes 😅\n"
            "Borrá alguna que no uses y volvé a intentar."
        )

    try:
        await run_in_threadpool(
            crear_categoria, user_id=user_id, nombre=nombre, tipo=tipo
        )
    except DBError as exc:
        logger.warning("No pude crear la categoría %r: %s", nombre, exc)
        return f"No pude crear la categoría 😕\n{exc}"

    ejemplo = {
        TipoMovimiento.GASTO: f"«pagué 25 lucas de {nombre}»",
        TipoMovimiento.INGRESO: f"«cobré 50 mil de {nombre}»",
        TipoMovimiento.AHORRO: f"«aparté 30 mil en {nombre}»",
        TipoMovimiento.INVERSION: f"«puse 100 mil en {nombre}»",
    }[tipo]

    return (
        f"Listo ✏️ Creé la categoría «{nombre}».\n"
        f"Es tuya y solo la ves vos. Ya la puedo usar: probá con {ejemplo}."
    )


async def _borrar_categoria(
    nombre: str,
    tipo: TipoMovimiento,
    vocabulario: Vocabulario,
    chat_id: int,
    user_id: str,
) -> str:
    """Baja una categoría propia, avisando si hay movimientos que la usan."""
    encontrada = vocabulario.resolver(nombre, tipo)

    if encontrada is None:
        propias = vocabulario.propias()
        if not propias:
            return (
                f"No tengo ninguna categoría que se llame «{nombre}» 🤔\n"
                "Y no tenés ninguna propia todavía: las que vienen por defecto "
                "no se borran."
            )
        lista = " · ".join(c.nombre for c in propias)
        return (
            f"No tengo ninguna categoría que se llame «{nombre}» 🤔\n"
            f"Las tuyas son: {lista}"
        )

    if not encontrada.propia:
        return (
            f"{encontrada.etiqueta} es una de las categorías base, esas no se "
            "borran 🙂\nSolo podés borrar las que creaste vos."
        )

    cantidad, totales = await run_in_threadpool(
        uso_de_categoria, user_id=user_id, categoria=encontrada.nombre, tipo=tipo
    )

    if not cantidad:
        try:
            await run_in_threadpool(
                borrar_categoria, user_id=user_id, nombre=encontrada.nombre, tipo=tipo
            )
        except DBError as exc:
            logger.warning("No pude borrar la categoría %r: %s", nombre, exc)
            return f"No pude borrarla 😕\n{exc}"
        return f"Listo 🗑 Borré «{encontrada.nombre}». No la estaba usando nada."

    pendientes.guardar(
        chat_id,
        pendientes.Pendiente(
            tipo="borrar_categoria",
            movimiento_id=0,
            mencion=encontrada.nombre,
            moneda=Moneda.ARS.value,
            datos={"tipo": tipo.value},
        ),
    )

    plata = " · ".join(
        _formatear_monto(monto, moneda)
        for moneda, monto in sorted(totales.items(), key=lambda kv: kv[0].value)
    )

    return (
        f"Tenés {cantidad} {'movimiento' if cantidad == 1 else 'movimientos'} en "
        f"«{encontrada.nombre}» por {plata} 🤔\n"
        "Si la borro, esos movimientos quedan igual y los gráficos no cambian: "
        "solo dejo de ofrecerla para los nuevos.\n\n"
        "Decime «borrala» para eso, «pasalos a otros» si querés además "
        "reetiquetarlos, o «dejalo» para no tocar nada."
    )


async def _resolver_pendiente(
    chat_id: int, pendiente, texto: str, user_id: str
) -> str | None:
    """Contesta la pregunta abierta, o None si el mensaje no la contestaba."""
    respuesta = texto.strip().lower()

    # Las de categoría van primero: ahí "no" quiere decir "dejalo en otros", no
    # "dejalo sin objetivo", y la respuesta sería confusa.
    if pendiente.tipo == "categoria":
        return await _resolver_pendiente_categoria(chat_id, pendiente, texto, user_id)

    if pendiente.tipo == "borrar_categoria":
        return await _resolver_pendiente_borrado(chat_id, pendiente, texto, user_id)

    if respuesta in {"no", "ninguno", "ninguna", "nada", "cancelar", "dejalo", "no importa"}:
        pendientes.olvidar(chat_id)
        return "Listo, lo dejo sin objetivo 👍"

    if pendiente.tipo == "elegir":
        elegido = _elegir_candidato(pendiente, respuesta)
        if elegido is None:
            return None

        pendientes.olvidar(chat_id)
        await run_in_threadpool(
            imputar_movimiento, pendiente.movimiento_id, elegido["id"], user_id=user_id
        )
        return await _texto_progreso(None, elegido, user_id)

    monto = parsear_monto(texto)
    if monto is None:
        return None

    try:
        objetivo = await run_in_threadpool(
            crear_objetivo,
            user_id=user_id,
            nombre=pendiente.mencion,
            monto_objetivo=monto,
            moneda=Moneda(pendiente.moneda),
        )
    except DBError as exc:
        pendientes.olvidar(chat_id)
        logger.warning("No se pudo crear el objetivo %r: %s", pendiente.mencion, exc)
        return f"No pude crear el objetivo 😕\n{exc}"

    pendientes.olvidar(chat_id)
    await run_in_threadpool(
        imputar_movimiento, pendiente.movimiento_id, objetivo["id"], user_id=user_id
    )
    return (
        f"Creé el objetivo «{objetivo['nombre']}» 🎯\n\n"
        + await _texto_progreso(None, objetivo, user_id)
    )


def _elegir_candidato(pendiente, respuesta: str) -> dict | None:
    """El candidato que eligió el usuario: por número o por nombre."""
    if respuesta.isdigit():
        indice = int(respuesta)
        if 1 <= indice <= len(pendiente.candidatos):
            return pendiente.candidatos[indice - 1]
        return None

    return buscar(respuesta, pendiente.candidatos).unico


async def _texto_progreso(
    movimiento: Movimiento | None, objetivo: dict, user_id: str
) -> str:
    """Ej: 'Sumé $150.000 al objetivo «Viaje a Europa». Vas 60%, te faltan $100.000.'"""
    moneda = Moneda(objetivo["moneda"])
    aportado = await run_in_threadpool(
        total_imputado, objetivo["id"], moneda, user_id=user_id
    )
    meta = Decimal(str(objetivo["monto_objetivo"]))
    porcentaje, falta, completo = progreso(aportado, meta)

    if movimiento is not None:
        cabeza = f"✅ Sumé {_formatear_monto(movimiento.monto, movimiento.moneda)}"
    else:
        cabeza = "✅ Imputado"

    linea = f"{cabeza} al objetivo «{objetivo['nombre']}»."

    if completo:
        return f"{linea}\n🎉 ¡Lo completaste! Llevás {_formatear_monto(aportado, moneda)}."
    return (
        f"{linea}\nVas {porcentaje}%, te faltan {_formatear_monto(falta, moneda)} "
        f"de {_formatear_monto(meta, moneda)}."
    )


_ETIQUETA_INVERSION = {
    "accion": "Acción",
    "etf": "ETF",
    "bono": "Bono",
    "cedear": "CEDEAR",
    "fci": "FCI",
    "cripto": "Cripto",
    "plazo_fijo": "Plazo fijo",
}

ETIQUETA_FALTANTE = {
    "tipo": "qué tipo de activo es (acción, cedear, cripto, bono, fci, plazo fijo)",
    "nombre": "qué compraste",
    "cantidad": "cuántas unidades compraste",
    "precio_compra": "a qué precio por unidad",
    "que_inversion": "cuál inversión cerraste (nombre o ticker)",
}

_ETIQUETA_TIPO = {
    "gasto": ("Gasto", "Gastaste", "Gastos"),
    "ingreso": ("Ingreso", "Cobraste", "Ingresos"),
    "ahorro": ("Ahorro", "Ahorraste", "Ahorros"),
    "inversion": ("Inversión", "Invertiste", "Inversiones"),
}


def _texto_total_por_tipo(consulta: Consulta, user_id: str) -> str:
    """Ej: '💸 Gastaste $123.400 este mes (14 movimientos)'."""
    totales = totales_por_moneda(
        user_id=user_id,
        desde=consulta.desde,
        hasta=consulta.hasta,
        tipo=consulta.tipo,
        moneda=consulta.moneda,
        categoria=consulta.categoria,
    )
    if not totales:
        return _sin_datos(consulta)

    verbo = _ETIQUETA_TIPO[consulta.tipo.value][1] if consulta.tipo else "Registraste"
    lineas = [f"{verbo} {consulta.etiqueta_periodo}:"]
    for moneda, total in sorted(totales.items(), key=lambda kv: kv[0].value):
        lineas.append(
            f"  {_formatear_monto(total.monto, moneda)} ({_plural(total.cantidad)})"
        )
    return "\n".join(lineas)


def _texto_por_categoria(consulta: Consulta, user_id: str) -> str:
    """Desglose por rubro, de mayor a menor, con el total al final."""
    desglose = totales_por_categoria(
        user_id=user_id,
        desde=consulta.desde,
        hasta=consulta.hasta,
        tipo=consulta.tipo,
        moneda=consulta.moneda,
    )
    if consulta.categoria:
        desglose = [fila for fila in desglose if fila[0] == consulta.categoria]

    if not desglose:
        return _sin_datos(consulta)

    encabezado = _ETIQUETA_TIPO[consulta.tipo.value][2] if consulta.tipo else "Movimientos"
    lineas = [f"{encabezado} {consulta.etiqueta_periodo}:"]

    for categoria, moneda, total in desglose[:TOPE_CATEGORIAS]:
        lineas.append(f"  {categoria}: {_formatear_monto(total.monto, moneda)}")

    restantes = desglose[TOPE_CATEGORIAS:]
    if restantes:
        lineas.append(f"  …y {len(restantes)} categorías más")

    totales: dict[Moneda, Decimal] = {}
    for _, moneda, total in desglose:
        totales[moneda] = totales.get(moneda, Decimal("0")) + total.monto
    for moneda, monto in sorted(totales.items(), key=lambda kv: kv[0].value):
        lineas.append(f"Total: {_formatear_monto(monto, moneda)}")

    return "\n".join(lineas)


def _texto_balance(consulta: Consulta, user_id: str) -> str:
    """Ingresos, gastos y la diferencia, por moneda."""
    resultado = balance(
        user_id=user_id,
        desde=consulta.desde,
        hasta=consulta.hasta,
        moneda=consulta.moneda,
    )
    if not resultado:
        return _sin_datos(consulta)

    lineas = [f"Balance {consulta.etiqueta_periodo}:"]
    for moneda, cifras in resultado.items():
        signo = "🟢" if cifras["balance"] >= 0 else "🔴"
        if len(resultado) > 1:
            lineas.append(f"— {moneda.value} —")
        lineas.extend(
            [
                f"  Ingresos: {_formatear_monto(cifras['ingresos'], moneda)}",
                f"  Gastos:   {_formatear_monto(cifras['gastos'], moneda)}",
                f"  {signo} Balance: {_formatear_monto(cifras['balance'], moneda)}",
            ]
        )
    lineas.append("(el ahorro y la inversión no cuentan como gasto)")
    return "\n".join(lineas)


def _sin_datos(consulta: Consulta) -> str:
    detalle = f" de {consulta.categoria}" if consulta.categoria else ""
    periodo = "" if consulta.etiqueta_periodo == "en total" else f" {consulta.etiqueta_periodo}"
    return f"No tengo movimientos{detalle}{periodo} 🤷"


def _plural(cantidad: int) -> str:
    return "1 movimiento" if cantidad == 1 else f"{cantidad} movimientos"


_SIMBOLO_MONEDA = {Moneda.ARS: "$", Moneda.USD: "US$", Moneda.EUR: "€"}


def _formatear_monto(monto: Decimal, moneda: Moneda) -> str:
    """8500.00 -> '$8.500' | 15340.50 USD -> 'US$15.340,50' | 200 EUR -> '€200'."""
    simbolo = _SIMBOLO_MONEDA.get(moneda, f"{moneda.value} ")
    signo = "-" if monto < 0 else ""
    monto = abs(monto)
    if monto == monto.to_integral_value():
        cuerpo = f"{int(monto):,}".replace(",", ".")
    else:
        cuerpo = f"{monto:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{simbolo}{cuerpo}"


def _confirmacion(movimiento: Movimiento) -> str:
    """Ej: '✅ Gasto de $8.500 en supermercado registrado (03/08)'."""
    etiqueta = _ETIQUETA_TIPO[movimiento.tipo.value][0]
    cuenta = f" · {movimiento.cuenta}" if movimiento.cuenta else ""
    return (
        f"✅ {etiqueta} de {_formatear_monto(movimiento.monto, movimiento.moneda)} "
        f"en {movimiento.categoria} registrado ({movimiento.fecha:%d/%m}){cuenta}"
    )


async def _responder(chat_id: int, texto: str) -> None:
    """Envía un mensaje absorbiendo los fallos: no hay a quién avisarle si falla."""
    try:
        await enviar_mensaje(chat_id, texto)
    except TelegramError:
        logger.exception("No pude responderle al chat %s", chat_id)
