"""App FastAPI: recibe los updates de Telegram, registra movimientos y responde consultas."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.config import CHATS_PERMITIDOS, WEBHOOK_SECRET
from app.db import Total, balance, guardar_movimiento, init_db, totales_por_categoria, totales_por_moneda
from app.models import Consulta, Intencion, Moneda, Movimiento
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
    "o preguntarme: «¿cuánto gasté este mes?»"
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
    logger.info("Cliente de Telegram cerrado")


app = FastAPI(title="Agente Cuenta", lifespan=lifespan)


@app.get("/")
async def salud() -> dict[str, str]:
    """Chequeo de vida, para monitoreo o para ver que levantó bien."""
    return {"status": "ok"}


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
        respuesta = await _resolver(interpretacion)
    except Exception:
        logger.exception("Error resolviendo la intención %s", interpretacion.intencion)
        await _responder(chat_id, MSG_ERROR_INTERNO)
        return

    await _responder(chat_id, respuesta)


async def _resolver(interpretacion: Interpretacion) -> str:
    """Ejecuta la intención y devuelve el texto a mandarle al usuario."""
    intencion = interpretacion.intencion

    if intencion is Intencion.REGISTRAR:
        movimiento = interpretacion.movimiento
        movimiento_id = await run_in_threadpool(guardar_movimiento, movimiento)
        logger.info("Movimiento %s guardado: %s", movimiento_id, movimiento)
        return _confirmacion(movimiento)

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
# Armado de las respuestas
# --------------------------------------------------------------------------

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


def _formatear_monto(monto: Decimal, moneda: Moneda) -> str:
    """8500.00 -> '$8.500' | 15340.50 USD -> 'US$15.340,50' (formato argentino)."""
    simbolo = "$" if moneda is Moneda.ARS else "US$"
    signo = "-" if monto < 0 else ""
    monto = abs(monto)
    if monto == monto.to_integral_value():
        cuerpo = f"{int(monto):,}".replace(",", ".")
    else:
        # Formateamos al estilo inglés y damos vuelta los separadores.
        cuerpo = f"{monto:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{simbolo}{cuerpo}"


def _confirmacion(movimiento: Movimiento) -> str:
    """Ej: '✅ Gasto de $8.500 en supermercado registrado (03/08)'."""
    etiqueta = _ETIQUETA_TIPO[movimiento.tipo.value][0]
    return (
        f"✅ {etiqueta} de {_formatear_monto(movimiento.monto, movimiento.moneda)} "
        f"en {movimiento.categoria} registrado ({movimiento.fecha:%d/%m})"
    )


async def _responder(chat_id: int, texto: str) -> None:
    """Envía un mensaje absorbiendo los fallos: no hay a quién avisarle si falla."""
    try:
        await enviar_mensaje(chat_id, texto)
    except TelegramError:
        logger.exception("No pude responderle al chat %s", chat_id)
