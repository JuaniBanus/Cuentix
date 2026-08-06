"""App FastAPI: recibe los updates de Telegram, registra movimientos y responde consultas."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import pendientes
from app.comandos import respuesta_directa
from app.config import ALERTAS_SECRET, CHATS_PERMITIDOS, ORIGENES_WEB, WEBHOOK_SECRET
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
from app.db import (
    DBError,
    Total,
    balance,
    crear_objetivo,
    guardar_inversion,
    guardar_movimiento,
    imputar_movimiento,
    init_db,
    obtener_objetivos,
    total_imputado,
    totales_por_categoria,
    totales_por_moneda,
)
from app.models import (
    Alerta,
    Consulta,
    Intencion,
    Inversion,
    Moneda,
    Movimiento,
    TipoAlerta,
    TipoInversion,
)
from app.objetivos import buscar, parsear_monto, progreso
from app.parser import Interpretacion, ParserError, interpretar_mensaje
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

# Cuántas categorías mostrar en el desglose antes de agrupar el resto.
TOPE_CATEGORIAS = 8


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y apagado de la app."""
    init_db()  # crea movimientos.db y la tabla si no existen (es idempotente)
    logger.info("Base de datos lista")
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
        allow_methods=["POST", "OPTIONS"],
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
# Estos dos endpoints NO piden sesión, al revés que /insights. Devuelven
# cotizaciones públicas, iguales para todos, sin nada del usuario. Lo que se
# protege es la clave, y para eso alcanza con que no salga del servidor.


@app.get("/api/precio")
async def api_precio(ticker: str, mercado: str = "us") -> dict:
    """Precio actual, variación diaria/semanal/mensual y máximos y mínimos.

    `mercado=us` (default) para NASDAQ/NYSE, `mercado=ar` para BYMA. No es un
    detalle: AAPL existe en los dos y son activos distintos, en monedas
    distintas y con precios que difieren por ochenta veces.
    """
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
async def api_historico(ticker: str, mercado: str = "us", dias: int = 90) -> dict:
    """Cierres diarios de un activo, del más viejo al más nuevo."""
    try:
        return await historico_de_mercado(ticker, mercado, dias)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.get("/api/indice")
async def api_indice(symbol: str) -> dict:
    """Valor de un índice. Acepta ^GSPC (S&P 500) y ^MERV (Merval)."""
    try:
        return await indice_de_mercado(symbol)
    except ValorInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SinClave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MercadoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.post("/tareas/alertas/{secret}")
async def revisar_alertas(secret: str) -> dict:
    """Revisa las alertas de precio y avisa las que se cumplieron.

    La dispara un cron externo, no una persona, así que va protegida por un
    secreto en la URL y no por una sesión: no hay nadie logueado del otro lado.
    Es el mismo criterio que el webhook de Telegram.

    Se ejecuta en el request y no en un BackgroundTask a propósito: el cron
    necesita saber si salió bien, y con 200-y-a-otra-cosa se enteraría siempre
    de que sí.
    """
    if not ALERTAS_SECRET or not secrets.compare_digest(secret, ALERTAS_SECRET):
        # 404 y no 403, igual que el webhook: no confirmamos que la ruta exista.
        logger.warning("Disparo de alertas con secreto inválido")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

    return await revisar_alertas_de_precio()


@app.get("/api/cuota")
async def api_cuota() -> dict:
    """Cuánto queda del cupo diario del proveedor. Para poder monitorearlo."""
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
    try:
        await verificar_sesion(authorization)
    except SesionInvalida as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        insights = await run_in_threadpool(generar_insights, datos)
    except InsightsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return {"insights": [i.model_dump() for i in insights]}


@app.post("/webhook/{secret}")
async def webhook(
    secret: str,
    request: Request,
    tareas: BackgroundTasks,
) -> dict[str, bool]:
    """Punto de entrada de los updates de Telegram.

    Contesta 200 enseguida y deja el trabajo lento (Gemini + base + respuesta)
    para un BackgroundTask. Telegram espera la respuesta del webhook y, si
    tarda o falla, reintenta el mismo update: si parseáramos acá, un reintento
    registraría el gasto dos veces.
    """
    # compare_digest y no ==: comparar strings con == corta en el primer
    # carácter distinto, y ese tiempo distinto permite adivinar el secreto.
    if not secrets.compare_digest(secret, WEBHOOK_SECRET):
        logger.warning("Webhook llamado con secreto inválido desde %s", request.client)
        # 404 y no 403: no confirmamos que la ruta exista.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    try:
        update = await request.json()
    except ValueError:
        # Body ilegible. Devolvemos 200 igual para que Telegram no reintente
        # eternamente algo que nunca vamos a poder procesar.
        logger.warning("Update con body que no es JSON")
        return {"ok": True}

    tareas.add_task(procesar_update, update)
    return {"ok": True}


async def procesar_update(update: Any) -> None:
    """Trabajo pesado, fuera del ciclo request/response.

    Nada de lo que pase acá puede propagar una excepción: la respuesta a
    Telegram ya se mandó, así que un error solo serviría para ensuciar el log
    y dejar al usuario sin respuesta.
    """
    # El filtro va antes que todo lo demás: a un chat ajeno no le contestamos
    # nada, ni siquiera "solo entiendo texto". Un bot que responde confirma que
    # existe e invita a seguir probando; uno mudo se abandona enseguida.
    chat_id = extraer_chat_id(update)
    if chat_id is not None and chat_id not in CHATS_PERMITIDOS:
        logger.warning("Mensaje ignorado: el chat %s no está autorizado", chat_id)
        return

    entrante = extraer_mensaje(update)

    if entrante is None:
        # Puede ser una foto o un sticker (contestamos), o algo sin chat
        # como un callback de botón o un update de otro tipo (ignoramos).
        if chat_id is not None:
            logger.info("Update sin texto en el chat %s", chat_id)
            await _responder(chat_id, MSG_SOLO_TEXTO)
        else:
            logger.debug("Update ignorado: %s", list(update) if isinstance(update, dict) else type(update))
        return

    chat_id, texto, _ = entrante
    logger.info("Mensaje de %s: %r", chat_id, texto)

    # Si el bot dejó una pregunta abierta ("¿a cuál de los dos?"), el mensaje
    # puede ser la respuesta. Va antes que todo lo demás porque un "1" o un
    # "300 mil" sueltos no significan nada fuera de ese contexto.
    #
    # Si no parece una respuesta, devuelve None y el mensaje sigue su camino
    # normal: nunca deja al usuario atrapado en la pregunta.
    pendiente = pendientes.mirar(chat_id)
    if pendiente is not None:
        try:
            respuesta = await _resolver_pendiente(chat_id, pendiente, texto)
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
        respuesta = await _resolver(interpretacion, chat_id)
    except Exception:
        logger.exception("Error resolviendo la intención %s", interpretacion.intencion)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    await _responder(chat_id, respuesta)


async def _resolver(interpretacion: Interpretacion, chat_id: int) -> str:
    """Ejecuta la intención y devuelve el texto a mandarle al usuario."""
    intencion = interpretacion.intencion

    if intencion is Intencion.REGISTRAR:
        movimiento = interpretacion.movimiento
        if interpretacion.objetivo:
            return await _registrar_hacia_objetivo(chat_id, movimiento, interpretacion.objetivo)

        movimiento_id = await run_in_threadpool(guardar_movimiento, movimiento)
        logger.info("Movimiento %s guardado: %s", movimiento_id, movimiento)
        return _confirmacion(movimiento)

    if intencion is Intencion.REGISTRAR_INVERSION:
        return await _resolver_inversion(interpretacion)

    if intencion is Intencion.CREAR_ALERTA:
        return await _resolver_alerta(interpretacion, chat_id)

    if intencion is Intencion.VER_ALERTAS:
        return await _texto_alertas(chat_id)

    if intencion is Intencion.DESCONOCIDA or interpretacion.consulta is None:
        return MSG_NO_ENTENDI

    consulta = interpretacion.consulta
    logger.info("Consulta %s: %s", intencion.value, consulta)

    if intencion is Intencion.TOTAL_POR_TIPO:
        return await run_in_threadpool(_texto_total_por_tipo, consulta)
    if intencion is Intencion.TOTAL_POR_CATEGORIA:
        return await run_in_threadpool(_texto_por_categoria, consulta)
    if intencion is Intencion.BALANCE:
        return await run_in_threadpool(_texto_balance, consulta)

    return MSG_NO_ENTENDI


# --------------------------------------------------------------------------
# Alertas de precio
# --------------------------------------------------------------------------


async def _resolver_alerta(interpretacion: Interpretacion, chat_id: int) -> str:
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
        crear_alerta, alerta, chat_id=chat_id, referencia=referencia, moneda=moneda
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


async def _texto_alertas(chat_id: int) -> str:
    """Las alertas activas de este chat."""
    filas = await run_in_threadpool(alertas_de_chat, chat_id)
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


async def _resolver_inversion(interpretacion: Interpretacion) -> str:
    """Guarda la compra, o pregunta por lo que falte en vez de inventarlo."""
    if interpretacion.faltantes:
        return _pedir_faltantes(interpretacion.faltantes)

    inversion = interpretacion.inversion
    inversion_id = await run_in_threadpool(guardar_inversion, inversion)
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


async def _registrar_hacia_objetivo(chat_id: int, movimiento: Movimiento, mencion: str) -> str:
    """Guarda el ahorro y, si puede, lo imputa. Si no, pregunta.

    El movimiento se guarda SIEMPRE, incluso cuando hay que preguntar: la plata
    se apartó igual, y perder el registro por una duda sobre a qué objetivo va
    sería el peor de los resultados.
    """
    objetivos = await run_in_threadpool(obtener_objetivos)
    coincidencias = buscar(mencion, objetivos)

    # Un solo objetivo coincide: es el único caso en que se puede imputar sin
    # preguntar nada.
    if coincidencias.unico is not None:
        objetivo = coincidencias.unico
        movimiento_id = await run_in_threadpool(guardar_movimiento, movimiento, objetivo["id"])
        logger.info("Movimiento %s imputado a %r", movimiento_id, objetivo["nombre"])
        return await _texto_progreso(movimiento, objetivo)

    movimiento_id = await run_in_threadpool(guardar_movimiento, movimiento)
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


async def _resolver_pendiente(chat_id: int, pendiente, texto: str) -> str | None:
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
        await run_in_threadpool(imputar_movimiento, pendiente.movimiento_id, elegido["id"])
        return await _texto_progreso(None, elegido)

    # tipo == "crear"
    monto = parsear_monto(texto)
    if monto is None:
        return None

    try:
        objetivo = await run_in_threadpool(
            crear_objetivo,
            nombre=pendiente.mencion,
            monto_objetivo=monto,
            moneda=Moneda(pendiente.moneda),
        )
    except DBError as exc:
        pendientes.olvidar(chat_id)
        logger.warning("No se pudo crear el objetivo %r: %s", pendiente.mencion, exc)
        return f"No pude crear el objetivo 😕\n{exc}"

    pendientes.olvidar(chat_id)
    await run_in_threadpool(imputar_movimiento, pendiente.movimiento_id, objetivo["id"])
    return f"Creé el objetivo «{objetivo['nombre']}» 🎯\n\n" + await _texto_progreso(None, objetivo)


def _elegir_candidato(pendiente, respuesta: str) -> dict | None:
    """El candidato que eligió el usuario: por número o por nombre."""
    if respuesta.isdigit():
        indice = int(respuesta)
        if 1 <= indice <= len(pendiente.candidatos):
            return pendiente.candidatos[indice - 1]
        return None

    # También vale escribir el nombre, si desempata solo.
    return buscar(respuesta, pendiente.candidatos).unico


async def _texto_progreso(movimiento: Movimiento | None, objetivo: dict) -> str:
    """Ej: 'Sumé $150.000 al objetivo «Viaje a Europa». Vas 60%, te faltan $100.000.'"""
    moneda = Moneda(objetivo["moneda"])
    aportado = await run_in_threadpool(total_imputado, objetivo["id"], moneda)
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


def _texto_total_por_tipo(consulta: Consulta) -> str:
    """Ej: '💸 Gastaste $123.400 este mes (14 movimientos)'."""
    totales = totales_por_moneda(
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


def _texto_por_categoria(consulta: Consulta) -> str:
    """Desglose por rubro, de mayor a menor, con el total al final."""
    desglose = totales_por_categoria(
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


def _texto_balance(consulta: Consulta) -> str:
    """Ingresos, gastos y la diferencia, por moneda."""
    resultado = balance(
        desde=consulta.desde, hasta=consulta.hasta, moneda=consulta.moneda
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
