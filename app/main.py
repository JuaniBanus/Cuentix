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
from app.limites import Limite, LimiteExcedido, identificar
from app.alertas import revisar as revisar_alertas_de_precio
from app.insights import AgregadosGastos, InsightsError
from app.insights import generar as generar_insights
from app.mercado import MercadoError, SinClave, ValorInvalido
from app.mercado import cerrar_cliente as cerrar_cliente_mercado
from app.mercado import historico as historico_de_mercado
from app.mercado import indice as indice_de_mercado
from app.mercado import precio as precio_de_mercado
from app.mercado import presupuesto as presupuesto_mercado
from app.sesion_web import SesionInvalida
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
    balance,
    cerrar_reto,
    claves_de_items,
    crear_objetivo,
    crear_reto,
    gastado_en_reto,
    reto_activo,
    historial_de_item,
    movimientos_para_termometro,
    guardar_inversion,
    guardar_movimiento,
    guardar_movimientos,
    imputar_movimiento,
    init_db,
    obtener_inversiones,
    obtener_objetivos,
    obtener_rendimientos,
    total_imputado,
    totales_por_categoria,
    totales_por_moneda,
)
from app.models import (
    Alerta,
    CompraHipotetica,
    Consulta,
    Financiacion,
    Intencion,
    Inversion,
    Moneda,
    Movimiento,
    PlanConsulta,
    TipoAlerta,
    TipoInversion,
    TipoMovimiento,
)
from app.objetivos import buscar, parsear_monto, progreso
from app.parser import Interpretacion, ParserError, interpretar_mensaje
from app.usuarios import Usuario
from app.usuarios import resolver as resolver_usuario
from app.recordatorio import atender_comando as atender_comando_recordatorio
from app.recordatorio import enviar_recordatorios
from app.recordatorio import es_comando as es_comando_recordatorio
from app.telegram import (
    TelegramError,
    cerrar_cliente,
    enviar_mensaje,
    extraer_chat_id,
    extraer_mensaje,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MSG_SOLO_TEXTO = (
    "Por ahora solo entiendo mensajes de texto 🙃\n"
    "Escribime algo como: «gasté 8 lucas en el super ayer»."
)
MSG_NO_ENTENDI = (
    "No entendí 🤔\n"
    "Podés anotar algo: «pagué 45 mil de luz»\n"
    "o preguntarme: «¿cuánto gasté este mes?»\n\n"
    "Escribí /ayuda para ver todo lo que puedo hacer."
)
MSG_ERROR_INTERNO = "Se me rompió algo 😬 Probá de nuevo en un ratito."

# Lo que ve quien no tiene acceso: ni vinculado, ni pausado, ni pendiente, ni
# "no pude consultar la base". Un solo texto para los cuatro casos, a propósito:
# decir cuál es le contaría a un desconocido si una cuenta existe.
#
# El chat_id va en el mensaje porque es el dato que el administrador necesita
# para dar de alta a alguien, y no es un secreto: es el número del propio chat,
# el mismo que devuelve cualquier bot de utilidades de Telegram.
MSG_SIN_ACCESO = (
    "No tengo tu acceso habilitado 🔒\n"
    "Contactá al administrador para que te dé de alta.\n\n"
    "Tu número de chat es {chat_id}"
)

# Cada cuánto se le repite ese mensaje al mismo chat.
#
# Contestarle a un desconocido es un cambio respecto de cómo venía el bot, que
# se quedaba mudo justamente para no confirmarle a nadie que existe. Se hace
# porque un usuario legítimo recién dado de alta necesita entender por qué no
# le contestan. El límite es la mitad del costo: quien insista veinte veces
# recibe una respuesta, no veinte, así que el bot no sirve de amplificador.
ESPERA_SIN_ACCESO = 30 * 60.0
_ultimo_aviso: dict[int, float] = {}

# Cuántos chats desconocidos se recuerdan para no repetirles el aviso.
#
# Sin tope, cada chat que escribe una vez deja una entrada para siempre. No es
# explotable barato —hacen falta cuentas de Telegram distintas—, pero es una
# fuga de memoria real en un proceso que vive semanas. Cuando se llena se limpia
# lo vencido, y si aun así sobra, lo más viejo: el castigo de olvidar a alguien
# es que reciba el aviso una vez más.
TOPE_AVISOS = 2_000

# Que la ruta vieja del webhook ya avisó. Una vez por arranque alcanza.
_aviso_webhook_viejo = False

# Cuántas categorías mostrar en el desglose antes de agrupar el resto.
TOPE_CATEGORIAS = 8

# --------------------------------------------------------------------------
# Cupos por cliente
# --------------------------------------------------------------------------
#
# Los dos frenan gasto, no acceso, y por eso se cuentan distinto.
#
# El de mercado va por IP: son datos públicos y lo que se protege es el cupo
# diario del proveedor, que es de todos. 30 por minuto deja pasar de sobra una
# pantalla de inversiones —que además pide en serie y contra el caché— y corta
# a quien quiera quemar las 700 llamadas del día.
#
# El de Gemini va por USUARIO y no por IP: acá ya hay sesión, así que se puede
# contar a la persona en vez de a la conexión. Una IP compartida no debería
# hacer que dos usuarios se roben el cupo entre sí.
LIMITE_MERCADO = Limite(30, 60.0, "mercado")
LIMITE_GEMINI = Limite(20, 3600.0, "gemini")


def _frenar(limite: Limite, clave: str) -> None:
    """Aplica un cupo y traduce el exceso a un 429 con Retry-After.

    El 429 con la cabecera es lo que un cliente educado sabe leer para esperar
    en vez de reintentar en bucle, que es lo que convierte un pico en un
    problema sostenido.
    """
    try:
        limite.revisar(clave)
    except LimiteExcedido as exc:
        logger.warning("Cupo de %s agotado por %s", limite.nombre, clave)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.espera)},
        ) from exc


async def _exigir_sesion(authorization: str | None) -> str:
    """El id del usuario dueño del token, o un 401 con el motivo."""
    try:
        return await verificar_sesion(authorization)
    except SesionInvalida as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


def _autorizar_tarea(authorization: str | None) -> None:
    """Comprueba el secreto de los cron, que viaja en la cabecera.

    ANTES iba en la URL (/tareas/alertas/<secreto>). Se movió acá porque la
    ruta completa queda escrita en el log de accesos de Render en cada corrida
    —una por hora—, y un secreto en un log deja de ser un secreto: lo ve
    cualquiera con acceso a los logs, y sobrevive a cualquier rotación que no
    incluya purgarlos.

    Una cabecera Authorization no se registra en el log de accesos.
    """
    if not ALERTAS_SECRET:
        logger.warning("Disparo de tarea con ALERTAS_SECRET sin configurar")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

    entregado = ""
    if authorization and authorization.lower().startswith("bearer "):
        entregado = authorization[7:].strip()

    # compare_digest incluso cuando falta el token: comparar contra "" también
    # tiene que tardar lo mismo que comparar contra un secreto equivocado.
    if not secrets.compare_digest(entregado, ALERTAS_SECRET):
        # 404 y no 403, igual que el webhook: no se confirma que la ruta exista.
        logger.warning("Disparo de tarea con secreto inválido")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y apagado de la app."""
    init_db()  # verifica que las tablas existan y sean accesibles
    logger.info("Base de datos lista")

    # Queda en el log del arranque cuál de los dos modos de acceso está activo.
    # Sin esto, un chat_id olvidado en el .env se ve igual que un usuario mal
    # dado de alta, y son dos problemas distintos con dos arreglos distintos.
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
    await cerrar_cliente()  # cierra el AsyncClient de httpx
    await cerrar_cliente_sesion()  # el que valida las sesiones de la web
    await cerrar_cliente_mercado()  # el del proxy de precios
    logger.info("Clientes HTTP cerrados")


app = FastAPI(title="Agente Cuenta", lifespan=lifespan)

# La web y el bot no comparten origen (la web es estática, el bot está en
# Render), así que sin esto el navegador bloquea el pedido de insights.
# La lista es blanca y explícita: el endpoint gasta cuota de Gemini y no
# conviene que lo pueda invocar cualquier página.
if ORIGENES_WEB:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ORIGENES_WEB),
        # GET hace falta desde que /api/precio pide sesión. Un GET sin cabeceras
        # propias es "simple" y el navegador lo manda sin preguntar, pero al
        # sumarle Authorization pasa a llevar preflight, y ahí sí se compara
        # contra esta lista. Sin GET acá, la pantalla de inversiones dejaría de
        # cargar precios con un error de CORS que no menciona a la cabecera.
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


# --------------------------------------------------------------------------
# Proxy de precios de mercado
# --------------------------------------------------------------------------
#
# Van en el backend del bot y no en una función serverless por el CACHÉ. El
# plan gratuito del proveedor da 800 llamadas por día, así que cachear es
# obligatorio, y el caché de app/mercado.py es un diccionario en memoria: sirve
# porque este proceso vive entre pedidos. En serverless cada invocación puede
# arrancar un proceso nuevo, el caché no sobreviviría y haría falta un KV
# aparte —otra cuenta, otro secreto, otra pieza que puede fallar—.
#
# Estos endpoints PIDEN SESIÓN, igual que /insights, aunque los datos que
# devuelven sean públicos.
#
# Antes no la pedían, con este razonamiento: son cotizaciones iguales para
# todos, así que no hay nada de nadie que proteger. El razonamiento era correcto
# sobre los DATOS y equivocado sobre el RECURSO. El plan gratuito da 700
# llamadas por día; sin sesión, cualquiera con la URL las quema en un par de
# horas a seis por minuto, y el efecto no es un error visible sino una pantalla
# de inversiones con precios viejos que no explica por qué está así.
#
# La sesión no es control de acceso al dato: es lo que hace que el cupo sea de
# los usuarios y no de internet. El cupo por IP de abajo cubre el resto.


@app.get("/api/precio")
async def api_precio(
    ticker: str,
    request: Request,
    mercado: str = "us",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Precio actual, variación diaria/semanal/mensual y máximos y mínimos.

    `mercado=us` (default) para NASDAQ/NYSE, `mercado=ar` para BYMA. No es un
    detalle: AAPL existe en los dos y son activos distintos, en monedas
    distintas y con precios que difieren por ochenta veces.
    """
    await _exigir_sesion(authorization)
    _frenar(LIMITE_MERCADO, identificar(request))

    try:
        return await precio_de_mercado(ticker, mercado)
    # El orden importa: las dos heredan de MercadoError y Python entra por la
    # primera que coincide, así que las específicas van antes que la general.
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
    await _exigir_sesion(authorization)
    _frenar(LIMITE_MERCADO, identificar(request))

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
    await _exigir_sesion(authorization)
    _frenar(LIMITE_MERCADO, identificar(request))

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
    """Revisa las alertas de precio y avisa las que se cumplieron.

    La dispara un cron externo, no una persona, así que va protegida por un
    secreto y no por una sesión: no hay nadie logueado del otro lado. El secreto
    viaja en la cabecera Authorization —ver _autorizar_tarea— y ya no en la
    ruta, que quedaba escrita en el log de accesos.

    Se ejecuta en el request y no en un BackgroundTask a propósito: el cron
    necesita saber si salió bien, y con 200-y-a-otra-cosa se enteraría siempre
    de que sí.
    """
    _autorizar_tarea(authorization)
    return await revisar_alertas_de_precio()


@app.post("/narrativa")
async def escribir_narrativa(
    datos: AgregadosMes,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Redacta el resumen del mes a partir de agregados.

    Mismo contrato que /insights: recibe NÚMEROS ya calculados por la web, no
    movimientos. Acá no se lee la base ni se sabe de quién son los datos; el
    token solo prueba que quien llama es un usuario y no cualquiera gastando
    nuestra cuota de Gemini.

    El texto no se guarda desde acá: lo guarda la web en `narrativas`, que es
    donde RLS puede atarlo a su dueño.
    """
    usuario = await _exigir_sesion(authorization)
    # Por usuario y no por IP: el token ya dice quién es, y así dos personas
    # detrás de la misma conexión no se gastan el cupo entre ellas.
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
    """Manda el recordatorio diario a quien le toque en esta hora.

    Lo llama un cron cada hora, no una persona: mismo criterio que las alertas
    de precio, y por eso comparte el secreto. Corre en el request y no en un
    BackgroundTask para que el cron pueda enterarse si algo falló.

    Cada hora y no una vez al día porque la hora la elige cada usuario en su
    zona, y porque un cron que llega tarde no puede perder el envío.
    """
    _autorizar_tarea(authorization)
    return await enviar_recordatorios()


@app.post("/tareas/rendimientos")
async def actualizar_tasas_billeteras(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Refresca las TNA de las billeteras virtuales desde la fuente pública.

    Mismo criterio que las alertas: lo llama un cron, va protegido por el mismo
    secreto en la URL y corre dentro del request para que el cron pueda saber si
    salió bien.

    Va en el threadpool porque `actualizar()` es sincrónica y bloqueante —baja
    33 MB de JSON y escribe en Supabase—, y sin eso frenaría el event loop
    entero: el bot dejaría de contestar mensajes durante varios segundos.

    Nunca devuelve un 5xx por culpa de la fuente. Si la API de terceros está
    caída, esto responde 200 con `ok: false` y el detalle: es información para
    el log del cron, no una falla de nuestro servicio. Las tasas anteriores
    quedan intactas.
    """
    _autorizar_tarea(authorization)
    return await run_in_threadpool(actualizar_rendimientos)


@app.get("/api/cuota")
async def api_cuota(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Cuánto queda del cupo diario del proveedor. Para poder monitorearlo.

    Pide sesión aunque no devuelva datos de nadie: decía en público cuánto cupo
    quedaba, que es precisamente el marcador que necesita mirar quien lo está
    agotando para saber si le está saliendo.
    """
    await _exigir_sesion(authorization)
    return presupuesto_mercado()


@app.post("/insights")
async def analizar_gastos(
    datos: AgregadosGastos,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, list]:
    """Interpreta agregados de gasto y devuelve observaciones.

    Recibe números ya calculados por la web, no movimientos: acá no se lee la
    base ni se sabe de quién son. La autorización sobre los datos ya la hizo
    RLS en el navegador; el token solo prueba que quien llama es un usuario y
    no cualquiera gastando nuestra cuota de Gemini.

    Se resuelve en el request y no en un BackgroundTask —al revés que el
    webhook— porque acá hay alguien esperando la respuesta en pantalla.
    """
    usuario = await _exigir_sesion(authorization)
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
        # Body ilegible. Devolvemos 200 igual para que Telegram no reintente
        # eternamente algo que nunca vamos a poder procesar.
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
    """Punto de entrada de los updates de Telegram, con el secreto en cabecera.

    Telegram manda `X-Telegram-Bot-Api-Secret-Token` en cada update si el
    webhook se registró pasándole `secret_token`. Es la forma preferible sobre
    ponerlo en la ruta: la URL entera queda en el log de accesos de Render, y un
    secreto en un log lo puede leer cualquiera que tenga acceso a los logs.

    Contesta 200 enseguida y deja el trabajo lento (Gemini + base + respuesta)
    para un BackgroundTask. Telegram espera la respuesta del webhook y, si
    tarda o falla, reintenta el mismo update: si parseáramos acá, un reintento
    registraría el gasto dos veces.
    """
    # compare_digest y no ==: comparar strings con == corta en el primer
    # carácter distinto, y ese tiempo distinto permite adivinar el secreto.
    # Se compara aunque falte la cabecera, para que tardar lo mismo no delate
    # la diferencia entre "no mandaste nada" y "mandaste algo equivocado".
    if not secrets.compare_digest(x_telegram_bot_api_secret_token or "", WEBHOOK_SECRET):
        logger.warning("Webhook llamado con secreto inválido desde %s", request.client)
        # 404 y no 403: no confirmamos que la ruta exista.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return await _recibir_update(request, tareas)


@app.post("/webhook/{secret}")
async def webhook_en_ruta(
    secret: str,
    request: Request,
    tareas: BackgroundTasks,
) -> dict[str, bool]:
    """La forma vieja: el secreto en la URL. Sigue viva para no cortar el bot.

    No se puede migrar sola, porque el otro extremo lo configura Telegram y eso
    vive fuera del repositorio: si esta ruta desapareciera al desplegar, el bot
    quedaría mudo hasta que alguien corriera setWebhook a mano.

    Registrá el webhook con `secret_token` (ver README) y esta ruta deja de
    recibir tráfico; ahí se puede borrar. El aviso de abajo sale una vez por
    arranque, para que no pase inadvertido y no llene el log.
    """
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
    """Trabajo pesado, fuera del ciclo request/response.

    Nada de lo que pase acá puede propagar una excepción: la respuesta a
    Telegram ya se mandó, así que un error solo serviría para ensuciar el log
    y dejar al usuario sin respuesta.
    """
    # De quién es este mensaje. Va antes que TODO lo demás —antes de mirar si
    # el update trae texto, antes de tocar la base— porque sin esta respuesta
    # no hay ninguna consulta que se pueda hacer: cada lectura y cada escritura
    # de app/db.py necesitan un user_id, y no existe un valor por defecto.
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

    if entrante is None:
        # Una foto o un sticker de alguien habilitado: se le contesta.
        logger.info("Update sin texto en el chat %s", chat_id)
        await _responder(chat_id, MSG_SOLO_TEXTO)
        return

    # El chat_id se desempaqueta en otra variable y se compara, en vez de pisar
    # el que ya se autorizó. Hoy las dos funciones de app/telegram.py miran el
    # mismo campo del update y siempre coinciden; si algún día dejaran de
    # hacerlo, sin esta comparación estaríamos autorizando un chat y
    # contestándole a otro, que es la peor forma de romper el aislamiento.
    chat_del_mensaje, texto, _ = entrante
    if chat_del_mensaje != chat_id:
        logger.error(
            "Update inconsistente: autoricé el chat %s y el mensaje dice %s",
            chat_id, chat_del_mensaje,
        )
        return

    logger.info("Mensaje de %s (%s): %r", chat_id, usuario.email, texto)

    # Si el bot dejó una pregunta abierta ("¿a cuál de los dos?"), el mensaje
    # puede ser la respuesta. Va antes que todo lo demás porque un "1" o un
    # "300 mil" sueltos no significan nada fuera de ese contexto.
    #
    # Si no parece una respuesta, devuelve None y el mensaje sigue su camino
    # normal: nunca deja al usuario atrapado en la pregunta.
    pendiente = pendientes.mirar(chat_id)
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

    # Saludos y comandos salen por texto fijo, antes del parser: un "hola" no
    # tiene nada que interpretar, y mandarlo a Gemini sería pagar una llamada
    # y esperarla para que conteste que no entendió.
    directa = respuesta_directa(texto)
    if directa is not None:
        logger.info("Respuesta fija para %r", texto)
        await _responder(chat_id, directa)
        return

    # /recordatorio necesita leer y escribir en la base, así que no puede vivir
    # en comandos.py, que es solo texto fijo. Pero sí va antes del parser: es
    # un comando, no algo que haya que interpretar.
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
        # interpretar_mensaje y las funciones de db son síncronas y bloqueantes
        # (HTTP a Gemini y sqlite3). Sin el threadpool frenarían el event loop
        # entero, y el webhook dejaría de contestar mientras tanto.
        interpretacion = await run_in_threadpool(interpretar_mensaje, texto)
    except ParserError as exc:
        logger.info("No se pudo interpretar %r: %s", texto, exc)
        await _responder(chat_id, MSG_NO_ENTENDI)
        return
    except Exception:
        logger.exception("Error inesperado interpretando %r", texto)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    try:
        respuesta = await _resolver(interpretacion, chat_id, usuario.user_id)
    except Exception:
        logger.exception("Error resolviendo la intención %s", interpretacion.intencion)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    await _responder(chat_id, respuesta)


async def _autorizar(chat_id: int) -> Usuario | None:
    """El usuario dueño del chat, o None si el mensaje no se procesa.

    Los cuatro motivos para devolver None terminan en el mismo mensaje neutro:

      - el chat no está en `usuarios_telegram` (nadie lo dio de alta);
      - está, pero el perfil quedó 'pausado' o 'pendiente';
      - el vínculo apunta a un usuario sin perfil (base inconsistente);
      - no se pudo consultar Supabase.

    Que el cuarto caso caiga acá adentro es deliberado: cuando no se sabe de
    quién es el mensaje, la única respuesta segura es no procesarlo. Un bot que
    "sigue igual" ante un error de red sería un bot que escribe movimientos sin
    dueño, o peor, en la cuenta equivocada.

    El precio es que una caída de Supabase se le muestra al usuario como si no
    tuviera acceso, que es confuso. Es el lado correcto para equivocarse, y el
    log dice cuál de los cuatro fue.
    """
    usuario = await run_in_threadpool(resolver_usuario, chat_id)

    if usuario is not None and usuario.habilitado:
        # El cerrojo opcional del .env, cuando está puesto. Va DESPUÉS de la
        # tabla y no antes: así el log de arriba ya dejó constancia de quién
        # era, y se puede ver que quedó afuera por la lista y no por la base.
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


async def _resolver(interpretacion: Interpretacion, chat_id: int, user_id: str) -> str:
    """Ejecuta la intención y devuelve el texto a mandarle al usuario."""
    intencion = interpretacion.intencion

    if intencion is Intencion.REGISTRAR:
        movimiento = await run_in_threadpool(
            _con_clave_item, interpretacion.movimiento, user_id
        )
        if interpretacion.objetivo:
            return await _registrar_hacia_objetivo(
                chat_id, movimiento, interpretacion.objetivo, user_id
            )

        # El aviso se busca ANTES de guardar: si no, la compra recién hecha
        # entraría en su propio historial y se compararía contra sí misma.
        aviso = await run_in_threadpool(_aviso_de_salto, movimiento, user_id)
        # También antes de guardar: el aviso suma el movimiento nuevo a mano,
        # y si ya estuviera en la base lo contaría dos veces.
        aviso_reto = await run_in_threadpool(_aviso_de_reto, movimiento, chat_id, user_id)
        movimiento_id = await run_in_threadpool(
            guardar_movimiento, movimiento, user_id=user_id
        )
        logger.info("Movimiento %s guardado: %s", movimiento_id, movimiento)
        return _confirmacion(movimiento) + aviso + aviso_reto

    if intencion is Intencion.REGISTRAR_VARIOS:
        return await _resolver_varios(interpretacion, user_id)

    if intencion is Intencion.REGISTRAR_INVERSION:
        return await _resolver_inversion(interpretacion, user_id)

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


# --------------------------------------------------------------------------
# Alertas de precio
# --------------------------------------------------------------------------


async def _resolver_alerta(
    interpretacion: Interpretacion, chat_id: int, user_id: str
) -> str:
    """Crea la alerta, o pregunta lo que falte."""
    if interpretacion.faltantes or not interpretacion.alerta:
        return _pedir_faltantes_alerta(interpretacion.faltantes)

    alerta = interpretacion.alerta

    # El precio de ahora es la referencia contra la que se miden después los
    # porcentajes. Se consulta ANTES de guardar: sin referencia, un "baja 5%"
    # no tendría contra qué compararse y la alerta no sonaría nunca.
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
        # Para debajo/encima el umbral es absoluto: la referencia es un lujo.
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
        # Indicativo y no subjuntivo: "si baja", no "si baje".
        verbo = "baja" if alerta.tipo is TipoAlerta.BAJA else "sube"
        # Se dice desde qué precio: "baja 5%" sin decir 5% de qué es ambiguo, y
        # es justo lo que la alerta va a medir.
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
    """Compara cuotas contra contado. No registra nada: todavía no compró.

    Es async porque cotizar la cartera sale a la red (CoinGecko y el proxy de
    mercado). Lo bloqueante —las tasas y la lectura de la base— va al
    threadpool para no frenar el event loop.
    """
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

    # El rendimiento de la cartera se calcula solo si hace falta: si el usuario
    # ya dijo a cuánto le rinde su plata, ese número manda y salir a cotizar
    # sería gastar cuota del proveedor para nada.
    cartera = None
    if tiene_inversiones and financiacion.tasa_mensual is None:
        try:
            cartera = await rendimiento_cartera(financiacion.moneda, user_id=user_id)
        except Exception:
            # Que no se pueda cotizar la cartera no puede dejar sin respuesta
            # una cuenta que ya está hecha con la tasa de plazo fijo.
            logger.warning("No pude calcular el rendimiento de la cartera", exc_info=True)

    return redactar_cuotas(comparacion, _formatear_monto, tiene_inversiones, cartera)


def _resolver_compra(compra: CompraHipotetica | None, user_id: str) -> str:
    """Analiza una compra hipotética. NO la registra: no pasó todavía."""
    if compra is None:
        return MSG_NO_ENTENDI

    logger.info("Compra hipotética: %s %s (%s)", compra.monto, compra.moneda.value, compra.que)
    return redactar_analisis(analizar_compra(compra, user_id=user_id), _formatear_monto)


def _resolver_plan(plan: PlanConsulta | None, user_id: str) -> str:
    """Ejecuta una pregunta analítica libre y devuelve la respuesta redactada.

    Si el plan pide comparar, se ejecuta DOS veces —una por período— y la
    diferencia se calcula en Python. No hay subconsulta ni SQL: comparar no
    amplía en nada lo que se puede pedir.
    """
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
    """Propone, acepta o informa el reto. Todo en un comando por simplicidad.

    Antes que nada revisa el reto abierto: si ya se cerró —por gasto o por
    fecha— hay que decirlo ahí, no dejar que el usuario descubra semanas
    después que lo perdió.
    """
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
        # Sigue abierto: no se propone otro encima.
        return texto_activo(abierto, gastado, _formatear_monto, Moneda(abierto.get("moneda", "ARS")))

    filas = movimientos_para_termometro(user_id=user_id)
    conteo: dict[str, int] = {}
    for fila in filas:
        conteo[fila.get("moneda", "ARS")] = conteo.get(fila.get("moneda", "ARS"), 0) + 1
    moneda = Moneda(max(conteo, key=conteo.get)) if conteo else Moneda.ARS

    propuesta = proponer_reto(filas, moneda.value)
    if propuesta is None:
        return texto_sin_propuesta()

    # /acepto crea; /reto solo muestra. Así aceptar es un acto explícito y no
    # algo que pasa por escribir una palabra.
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
    # En un grupo Telegram manda "/recurrentes@Cuentix_Bot".
    clave = (texto or "").strip().lower().split("@", 1)[0]
    return clave in _COMANDOS_RECURRENTES


def _texto_recurrentes(user_id: str) -> str:
    """Los cargos que se repiten, con la sugerencia de revisarlos."""
    try:
        filas = movimientos_para_termometro(user_id=user_id)
    except Exception:
        logger.exception("No pude leer los movimientos para recurrentes")
        return MSG_ERROR_INTERNO

    # Se mira la moneda con más movimientos: es donde está la vida del usuario.
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

# Cuántas mostrar por Telegram. La web las lista todas; acá un mensaje con
# treinta filas no se lee, y lo que se quiere saber es quién paga más.
TOPE_RENDIMIENTOS = 10


def _es_comando_rendimientos(texto: str) -> bool:
    clave = (texto or "").strip().lower().split("@", 1)[0]
    return clave in _COMANDOS_RENDIMIENTOS


def _texto_rendimientos() -> str:
    """El ranking de billeteras por TNA, con la fecha del dato bien visible.

    La fecha no es un adorno: estas tasas las refresca un cron contra una API de
    terceros, y si esa fuente se rompe el usuario tiene que poder darse cuenta
    de que está mirando algo viejo antes de mover la plata.
    """
    filas = obtener_rendimientos(limite=TOPE_RENDIMIENTOS)

    if not filas:
        return (
            "Todavía no tengo tasas de billeteras cargadas 🤷\n\n"
            "Las actualiza un proceso automático una vez por día. Si recién "
            "arrancaste, esperá a la próxima corrida."
        )

    # La más VIEJA de todas, no la más nueva: si una sola quedó atrasada, el
    # conjunto está atrasado. Redondear para el lado optimista sería justo lo
    # que hace que un dato podrido pase desapercibido.
    fechas = [f["fecha_actualizacion"] for f in filas if f.get("fecha_actualizacion")]
    mas_vieja = min(fechas) if fechas else None

    lineas = ["💰 Rendimientos de billeteras\n"]

    for puesto, fila in enumerate(filas, start=1):
        try:
            tna = Decimal(str(fila["tna"]))
        except (KeyError, ValueError, ArithmeticError):
            continue

        # Coma decimal, como todos los números que manda el bot.
        tna_txt = f"{tna:.2f}".replace(".", ",")
        # La TNA es nominal con capitalización a 30 días: el mes es TNA/12.
        # Mismo criterio que app/tasas.py, para que los dos digan lo mismo.
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
    """Le agrega al movimiento la clave con la que se agrupa su ítem.

    Se calcula ACÁ y se guarda en la fila, en vez de derivarla al consultar:
    el algoritmo de agrupación mira las claves existentes, así que recalcularlo
    después daría resultados distintos a medida que crece el historial y el
    termómetro cambiaría de números sin que nadie toque nada.
    """
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
    """La línea extra cuando el ítem se despegó de lo que venía saliendo.

    Se compara precio unitario contra precio unitario, o total contra total,
    pero nunca uno contra otro: son magnitudes distintas y mezclarlas daría un
    salto inventado.
    """
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
            continue  # $ y US$ no se comparan entre sí
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


async def _resolver_varios(interpretacion: Interpretacion, user_id: str) -> str:
    """Guarda los movimientos que vinieron completos y pregunta por el resto.

    Lo que está claro se guarda SIEMPRE, aunque otro ítem del mismo mensaje
    haya quedado en duda. Frenar los tres porque uno no se entendió obligaría
    al usuario a reescribir todo, que es justo lo que este modo evita.
    """
    movimientos = list(interpretacion.movimientos)
    dudas = interpretacion.dudas

    if not movimientos:
        return _texto_dudas(dudas, ninguno_guardado=True)

    ids = await run_in_threadpool(guardar_movimientos, movimientos, user_id=user_id)
    logger.info("Movimientos guardados en lote: %s", ids)

    return _texto_resumen(movimientos, dudas)


def _texto_resumen(
    movimientos: list[Movimiento], dudas: tuple[tuple[str, str], ...]
) -> str:
    """Ej: '✅ Registré 3 gastos por $37.000' + el detalle + lo que quedó en duda."""
    # Los totales van por tipo y por moneda: un mensaje puede traer dos gastos
    # en pesos y un ingreso en dólares, y "3 movimientos por $X" mezclaría
    # plata que entra con plata que sale.
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


def _pedir_faltantes(faltantes: tuple[str, ...]) -> str:
    """Pide los datos que faltan.

    El bot no guarda estado entre mensajes, así que pide la frase completa de
    nuevo en vez de esperar una respuesta suelta: un "a 25 dólares" aislado
    llegaría sin nada a lo que engancharse.
    """
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
    """Ej: '📈 Compra registrada\\n0,5 BTC (Bitcoin) a US$60.000\\nTotal: US$30.000'."""
    etiqueta = _ETIQUETA_INVERSION[inversion.tipo.value]
    total = inversion.cantidad * inversion.precio_compra
    identidad = (
        f"{inversion.ticker} ({inversion.nombre})" if inversion.ticker else inversion.nombre
    )

    # En un plazo fijo la "cantidad" es la plata depositada y no hay precio
    # unitario: mostrarlo daría "$0 por unidad · Total: $0", que no dice nada.
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
    # normalize() pasa los enteros a notación científica (10 -> 1E+1).
    if normalizada == normalizada.to_integral_value():
        return f"{int(normalizada):,}".replace(",", ".")
    return format(normalizada, "f").replace(".", ",")


# --------------------------------------------------------------------------
# Ahorros imputados a un objetivo
# --------------------------------------------------------------------------


async def _registrar_hacia_objetivo(
    chat_id: int, movimiento: Movimiento, mencion: str, user_id: str
) -> str:
    """Guarda el ahorro y, si puede, lo imputa. Si no, pregunta.

    El movimiento se guarda SIEMPRE, incluso cuando hay que preguntar: la plata
    se apartó igual, y perder el registro por una duda sobre a qué objetivo va
    sería el peor de los resultados.
    """
    objetivos = await run_in_threadpool(obtener_objetivos, user_id=user_id)
    coincidencias = buscar(mencion, objetivos)

    # Un solo objetivo coincide: es el único caso en que se puede imputar sin
    # preguntar nada.
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

    # No hay ninguno: se ofrece crearlo, pero no se inventa.
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


async def _resolver_pendiente(
    chat_id: int, pendiente, texto: str, user_id: str
) -> str | None:
    """Contesta la pregunta abierta, o None si el mensaje no la contestaba.

    None es importante: significa "esto era otra cosa", y el mensaje sigue al
    parser como cualquier otro. Sin esa salida, un usuario que cambia de tema
    quedaría atrapado contestando una pregunta que ya no le interesa.
    """
    respuesta = texto.strip().lower()

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

    # tipo == "crear"
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

    # También vale escribir el nombre, si desempata solo.
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


# --------------------------------------------------------------------------
# Armado de las respuestas
# --------------------------------------------------------------------------

_ETIQUETA_INVERSION = {
    "accion": "Acción",
    "etf": "ETF",
    "bono": "Bono",
    "cedear": "CEDEAR",
    "fci": "FCI",
    "cripto": "Cripto",
    "plazo_fijo": "Plazo fijo",
}

# Nombre técnico -> cómo pedírselo al usuario.
ETIQUETA_FALTANTE = {
    "tipo": "qué tipo de activo es (acción, cedear, cripto, bono, fci, plazo fijo)",
    "nombre": "qué compraste",
    "cantidad": "cuántas unidades compraste",
    "precio_compra": "a qué precio por unidad",
}

# (singular para la confirmación, verbo para los totales, plural para el desglose)
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
    # Si preguntó por una categoría puntual, filtramos acá para poder decirle
    # que esa categoría no tiene movimientos, en vez de mostrarle todas.
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
        # Con dos monedas en juego, sin este encabezado los bloques se
        # confunden entre sí y no se sabe cuál es cuál.
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
    # "en total" es el default cuando la pregunta no acota el tiempo; ponerlo
    # en la respuesta suena raro ("no tengo movimientos de yates en total").
    periodo = "" if consulta.etiqueta_periodo == "en total" else f" {consulta.etiqueta_periodo}"
    return f"No tengo movimientos{detalle}{periodo} 🤷"


def _plural(cantidad: int) -> str:
    return "1 movimiento" if cantidad == 1 else f"{cantidad} movimientos"


# El fallback etiqueta con el código en vez de romper o mentir: una moneda
# nueva en el enum sin símbolo acá se mostraría bien igual, solo que menos
# lindo. El ternario anterior rotulaba cualquier cosa que no fuera ARS como
# "US$", así que los euros salían disfrazados de dólares.
_SIMBOLO_MONEDA = {Moneda.ARS: "$", Moneda.USD: "US$", Moneda.EUR: "€"}


def _formatear_monto(monto: Decimal, moneda: Moneda) -> str:
    """8500.00 -> '$8.500' | 15340.50 USD -> 'US$15.340,50' | 200 EUR -> '€200'."""
    simbolo = _SIMBOLO_MONEDA.get(moneda, f"{moneda.value} ")
    signo = "-" if monto < 0 else ""
    monto = abs(monto)
    if monto == monto.to_integral_value():
        cuerpo = f"{int(monto):,}".replace(",", ".")
    else:
        # Formateamos al estilo inglés y damos vuelta los separadores.
        cuerpo = f"{monto:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{simbolo}{cuerpo}"


def _confirmacion(movimiento: Movimiento) -> str:
    """Ej: '✅ Gasto de $8.500 en supermercado registrado (03/08)'.

    Con cuenta: '✅ Ahorro de $50.000 en plazo fijo registrado (04/08) · banco'.
    Se muestra solo cuando el usuario la dijo, para que se vea que quedó
    anotada y no haya que ir a mirar la base para saberlo.
    """
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
