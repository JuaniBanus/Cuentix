"""Cliente de la Bot API de Telegram."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

import httpx

from app.config import TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

LIMITE_TEXTO = 4096

_cliente: httpx.AsyncClient | None = None


class TelegramError(RuntimeError):
    """Falló una llamada a la Bot API."""


class ArchivoDemasiadoGrande(TelegramError):
    """El archivo pasa el tope que aceptamos bajar."""


class MensajeEntrante(NamedTuple):
    """Lo mínimo que necesitamos de un update para procesarlo."""

    chat_id: int
    texto: str
    message_id: int


class VozEntrante(NamedTuple):
    """Un audio que todavía no bajamos: lo que Telegram cuenta de él.

    `duracion` y `tamano` vienen en el update, antes de descargar nada. Eso
    permite rechazar un audio de media hora sin gastar la descarga ni la cuota
    de Gemini.
    """

    chat_id: int
    message_id: int
    file_id: str
    duracion: int
    mime: str
    tamano: int


def _ocultar_token(texto: str) -> str:
    """El token aparece en la URL, y httpx la incluye en varias excepciones."""
    return texto.replace(TELEGRAM_TOKEN, "<TOKEN>")


def _obtener_cliente() -> httpx.AsyncClient:
    """Cliente httpx compartido, creado perezosamente."""
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
    """Parte un texto largo en varios mensajes, cortando por salto de línea"""
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = restante.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if restante:
        partes.append(restante)
    return partes


async def _llamar(metodo: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a un método de la Bot API. Devuelve el contenido de `result`."""
    cliente = _obtener_cliente()
    try:
        respuesta = await cliente.post(f"/{metodo}", json=payload)
        cuerpo = respuesta.json()
    except httpx.HTTPError as exc:
        logger.exception("Error de red llamando a %s", metodo)
        raise TelegramError(
            f"No pude comunicarme con Telegram ({metodo}): {_ocultar_token(str(exc))}"
        ) from exc
    except ValueError as exc:
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
    """Manda un mensaje de texto al chat indicado."""
    if not texto or not texto.strip():
        raise TelegramError("No se puede enviar un mensaje vacío.")

    enviados: list[dict[str, Any]] = []
    for i, parte in enumerate(_partir_texto(texto)):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": parte}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if silencioso:
            payload["disable_notification"] = True
        if responder_a is not None and i == 0:
            payload["reply_parameters"] = {"message_id": responder_a}

        enviados.append(await _llamar("sendMessage", payload))

    return enviados


async def descargar_archivo(file_id: str, tope_bytes: int) -> bytes:
    """Baja un archivo del chat. Dos pasos: getFile y después el contenido.

    `tope_bytes` se chequea contra lo que declara getFile y otra vez contra lo
    que llega de verdad: el primero evita la descarga, el segundo cubre que el
    tamaño declarado mienta o no venga.
    """
    datos = await _llamar("getFile", {"file_id": file_id})

    ruta = datos.get("file_path")
    if not isinstance(ruta, str) or not ruta:
        raise TelegramError("Telegram no me dijo dónde está el archivo.")

    declarado = datos.get("file_size")
    if isinstance(declarado, int) and declarado > tope_bytes:
        raise ArchivoDemasiadoGrande(
            f"El archivo pesa {declarado} bytes y el tope es {tope_bytes}."
        )

    cliente = _obtener_cliente()
    try:
        # URL absoluta: el contenido no cuelga de /bot<token> sino de
        # /file/bot<token>, así que no sirve el base_url del cliente.
        respuesta = await cliente.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{ruta}",
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        respuesta.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Error bajando el archivo %s", file_id)
        raise TelegramError(
            f"No pude bajar el archivo: {_ocultar_token(str(exc))}"
        ) from exc

    contenido = respuesta.content
    if len(contenido) > tope_bytes:
        raise ArchivoDemasiadoGrande(
            f"El archivo pesa {len(contenido)} bytes y el tope es {tope_bytes}."
        )
    if not contenido:
        raise TelegramError("El archivo vino vacío.")

    return contenido


def extraer_mensaje(update: Any) -> MensajeEntrante | None:
    """Saca chat_id, texto y message_id del JSON crudo de un update."""
    if not isinstance(update, dict):
        return None

    mensaje = update.get("message") or update.get("edited_message")
    if not isinstance(mensaje, dict):
        return None

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


def extraer_voz(update: Any) -> VozEntrante | None:
    """El audio de un update, o None si el mensaje no trae ninguno.

    Toma tanto `voice` (la nota de voz del micrófono, que es el caso normal)
    como `audio` (un archivo mandado como adjunto), porque para el usuario las
    dos cosas son «le mandé un audio». `video_note` queda afuera a propósito:
    es un video y pesa otra cosa.
    """
    if not isinstance(update, dict):
        return None

    mensaje = update.get("message") or update.get("edited_message")
    if not isinstance(mensaje, dict):
        return None

    audio = mensaje.get("voice") or mensaje.get("audio")
    if not isinstance(audio, dict):
        return None

    file_id = audio.get("file_id")
    if not isinstance(file_id, str) or not file_id:
        return None

    chat = mensaje.get("chat")
    if not isinstance(chat, dict):
        return None

    chat_id = chat.get("id")
    message_id = mensaje.get("message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return None

    duracion = audio.get("duration")
    tamano = audio.get("file_size")
    mime = audio.get("mime_type")

    return VozEntrante(
        chat_id=chat_id,
        message_id=message_id,
        file_id=file_id,
        # Los tres son opcionales en la Bot API. Si no vienen, cero y cadena
        # vacía: el que decide qué hacer con eso es quien llama.
        duracion=duracion if isinstance(duracion, int) else 0,
        mime=mime if isinstance(mime, str) and mime else "",
        tamano=tamano if isinstance(tamano, int) else 0,
    )


def extraer_chat_id(update: Any) -> int | None:
    """chat_id de cualquier update que venga de un chat, tenga texto o no."""
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
