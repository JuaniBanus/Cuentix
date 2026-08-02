"""Cliente de la Bot API de Telegram.

Dos responsabilidades: mandar mensajes salientes (`enviar_mensaje`) y leer los
updates entrantes del webhook (`extraer_mensaje`).
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

import httpx

from app.config import TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Telegram rechaza con 400 los mensajes de más de 4096 caracteres.
LIMITE_TEXTO = 4096

_cliente: httpx.AsyncClient | None = None


class TelegramError(RuntimeError):
    """Falló una llamada a la Bot API."""


class MensajeEntrante(NamedTuple):
    """Lo mínimo que necesitamos de un update para procesarlo."""

    chat_id: int
    texto: str
    message_id: int


def _ocultar_token(texto: str) -> str:
    """El token aparece en la URL, y httpx la incluye en varias excepciones.

    Sin esto, un `logger.exception` termina escribiendo el token en los logs.
    """
    return texto.replace(TELEGRAM_TOKEN, "<TOKEN>")


def _obtener_cliente() -> httpx.AsyncClient:
    """Cliente httpx compartido, creado perezosamente.

    Se crea en el primer uso y no al importar, porque un AsyncClient debe
    nacer dentro del event loop que lo va a usar. Reutilizarlo mantiene viva
    la conexión TCP/TLS con Telegram entre mensajes.
    """
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
    return _cliente


async def cerrar_cliente() -> None:
    """Cierra el cliente. Llamar desde el shutdown/lifespan de FastAPI."""
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


def _partir_texto(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Parte un texto largo en varios mensajes, cortando por salto de línea
    o espacio cuando se puede, para no partir palabras al medio."""
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = restante.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite  # una sola palabra gigante: cortamos y listo
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if restante:
        partes.append(restante)
    return partes


async def _llamar(metodo: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a un método de la Bot API. Devuelve el contenido de `result`.

    La Bot API responde siempre con {"ok": bool, ...}. Un `ok: false` puede
    venir con HTTP 200, así que no alcanza con mirar el código de estado.
    """
    cliente = _obtener_cliente()
    try:
        respuesta = await cliente.post(f"/{metodo}", json=payload)
        cuerpo = respuesta.json()
    except httpx.HTTPError as exc:
        logger.exception("Error de red llamando a %s", metodo)
        raise TelegramError(
            f"No pude comunicarme con Telegram ({metodo}): {_ocultar_token(str(exc))}"
        ) from exc
    except ValueError as exc:  # respuesta que no es JSON
        logger.exception("Telegram devolvió algo que no es JSON en %s", metodo)
        raise TelegramError(f"Respuesta ilegible de Telegram ({metodo}).") from exc

    if not cuerpo.get("ok"):
        descripcion = cuerpo.get("description", "sin detalle")
        codigo = cuerpo.get("error_code", respuesta.status_code)
        logger.error("Telegram rechazó %s: %s (%s)", metodo, descripcion, codigo)
        raise TelegramError(f"Telegram rechazó {metodo}: {descripcion} (error {codigo})")

    return cuerpo.get("result", {})


async def enviar_mensaje(
    chat_id: int,
    texto: str,
    *,
    parse_mode: str | None = None,
    responder_a: int | None = None,
    silencioso: bool = False,
) -> list[dict[str, Any]]:
    """Manda un mensaje de texto al chat indicado.

    Si el texto supera los 4096 caracteres se manda en varios mensajes.

    Args:
        chat_id: destinatario (viene del update).
        texto: contenido a enviar.
        parse_mode: "MarkdownV2" o "HTML" para formato. Ojo: con MarkdownV2 hay
            que escapar . - ! ( ) etc., o Telegram devuelve 400.
        responder_a: message_id al que responder, para que quede citado.
        silencioso: envía sin sonido de notificación.

    Returns:
        La lista de mensajes creados (uno por fragmento).

    Raises:
        TelegramError: si falla la red o si la API responde ok: false.
    """
    if not texto or not texto.strip():
        raise TelegramError("No se puede enviar un mensaje vacío.")

    enviados: list[dict[str, Any]] = []
    for i, parte in enumerate(_partir_texto(texto)):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": parte}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if silencioso:
            payload["disable_notification"] = True
        # El "responder a" solo tiene sentido en el primer fragmento.
        if responder_a is not None and i == 0:
            payload["reply_parameters"] = {"message_id": responder_a}

        enviados.append(await _llamar("sendMessage", payload))

    return enviados


def extraer_mensaje(update: Any) -> MensajeEntrante | None:
    """Saca chat_id, texto y message_id del JSON crudo de un update.

    Devuelve None —sin lanzar excepciones— cuando el update no trae un mensaje
    de texto utilizable: fotos, stickers, ubicaciones, entradas/salidas de
    miembros, callbacks de botones, o JSON con una forma inesperada.

    Acepta también `edited_message`: si el usuario corrige un mensaje mal
    tipeado, Telegram manda ese campo en lugar de `message`.
    """
    if not isinstance(update, dict):
        return None

    mensaje = update.get("message") or update.get("edited_message")
    if not isinstance(mensaje, dict):
        return None

    # Una foto o un sticker llegan como "message" válido pero sin "text".
    texto = mensaje.get("text")
    if not isinstance(texto, str) or not texto.strip():
        return None

    chat = mensaje.get("chat")
    if not isinstance(chat, dict):
        return None

    chat_id = chat.get("id")
    message_id = mensaje.get("message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return None

    return MensajeEntrante(chat_id=chat_id, texto=texto.strip(), message_id=message_id)


def extraer_chat_id(update: Any) -> int | None:
    """chat_id de cualquier update que venga de un chat, tenga texto o no.

    `extraer_mensaje` devuelve None ante una foto o un sticker, y ahí nos
    quedamos sin saber a quién contestarle. Esto rescata el chat_id igual,
    para poder responder "por ahora solo entiendo texto".
    """
    if not isinstance(update, dict):
        return None

    contenedores = [
        update.get(clave)
        for clave in ("message", "edited_message", "channel_post", "edited_channel_post")
    ]
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        contenedores.append(callback.get("message"))

    for contenedor in contenedores:
        if not isinstance(contenedor, dict):
            continue
        chat = contenedor.get("chat")
        if isinstance(chat, dict) and isinstance(chat.get("id"), int):
            return chat["id"]

    return None
