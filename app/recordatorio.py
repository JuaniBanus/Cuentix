"""Recordatorio diario: "¿Cómo fue tu día? Contame lo que gastaste." """

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db import (
    DBError,
    guardar_recordatorio,
    marcar_recordatorio_enviado,
    obtener_recordatorio,
    recordatorios_activos,
)

logger = logging.getLogger(__name__)

ZONA_POR_DEFECTO = "America/Argentina/Buenos_Aires"
HORA_POR_DEFECTO = 21

MSG_RECORDATORIO = (
    "🌙 ¿Cómo fue tu día?\n"
    "Contame lo que gastaste y lo registro.\n\n"
    "Podés mandarme todo junto:\n"
    "«gasté 5 lucas en el súper, 2 en un café y cargué 30 de nafta»"
)

_COMANDO = re.compile(
    r"^/recordatorio(?:@\w+)?\s*(?P<resto>.*)$", re.IGNORECASE | re.DOTALL
)
_HORA = re.compile(r"^(?P<hora>\d{1,2})\s*(?::\s*(?P<minutos>\d{2}))?\s*(?:hs?|horas?)?$")
_APAGAR = {"off", "no", "nunca", "apagar", "apagalo", "basta", "cancelar", "0ff"}


def es_comando(texto: str) -> bool:
    return bool(_COMANDO.match((texto or "").strip()))


def atender_comando(chat_id: int, texto: str, user_id: str) -> str:
    """Resuelve /recordatorio y devuelve qué contestarle al usuario."""
    coincidencia = _COMANDO.match(texto.strip())
    resto = (coincidencia.group("resto") or "").strip().lower() if coincidencia else ""

    try:
        if not resto:
            return _estado(chat_id, user_id)
        if resto in _APAGAR:
            return _apagar(chat_id, user_id)

        hora = _leer_hora(resto)
        if hora is None:
            return (
                "No entendí la hora 🤔\n"
                "Probá: /recordatorio 21  ·  /recordatorio 9:00  ·  /recordatorio off"
            )
        return _fijar(chat_id, hora, user_id)
    except DBError as exc:
        logger.error("Recordatorio: %s", exc)
        return "No pude guardar el recordatorio 😬 Probá de nuevo en un ratito."


def _leer_hora(texto: str) -> int | None:
    """"21", "21:00", "9hs" -> 21, 21, 9. Los minutos se ignoran a propósito."""
    coincidencia = _HORA.match(texto)
    if not coincidencia:
        return None
    hora = int(coincidencia.group("hora"))
    return hora if 0 <= hora <= 23 else None


def _fijar(chat_id: int, hora: int, user_id: str) -> str:
    guardar_recordatorio(chat_id, user_id=user_id, hora=hora, activo=True)
    return (
        f"🌙 Listo, te escribo todos los días a las {hora}:00.\n"
        "Me contás cómo te fue y anoto todo junto.\n\n"
        "Para cambiarlo: /recordatorio 22 · Para apagarlo: /recordatorio off"
    )


def _apagar(chat_id: int, user_id: str) -> str:
    guardar_recordatorio(chat_id, user_id=user_id, activo=False)
    return "Listo, no te escribo más 🤐\nPara volver a prenderlo: /recordatorio 21"


def _estado(chat_id: int, user_id: str) -> str:
    config = obtener_recordatorio(chat_id, user_id=user_id)
    if config and config.get("activo"):
        return (
            f"🌙 Te escribo todos los días a las {config['hora']}:00.\n\n"
            "Cambiarlo: /recordatorio 22 · Apagarlo: /recordatorio off"
        )
    return (
        "No tenés recordatorio activo.\n\n"
        f"Prendelo con /recordatorio {HORA_POR_DEFECTO} y te escribo todas las "
        "noches para que me cuentes cómo te fue."
    )


def _ahora_en(zona: str) -> datetime:
    """La hora local de esa zona. Si el nombre no existe, cae a la de acá."""
    try:
        tz = ZoneInfo(zona or ZONA_POR_DEFECTO)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Zona horaria desconocida: %r, uso %s", zona, ZONA_POR_DEFECTO)
        tz = ZoneInfo(ZONA_POR_DEFECTO)
    return datetime.now(timezone.utc).astimezone(tz)


def _le_toca(config: dict) -> bool:
    """¿A este chat le corresponde el aviso en esta corrida?"""
    ahora = _ahora_en(config.get("zona_horaria"))
    if ahora.hour != int(config.get("hora", HORA_POR_DEFECTO)):
        return False
    return config.get("ultimo_envio") != ahora.date().isoformat()


async def enviar_recordatorios() -> dict:
    """Manda el aviso a los chats a los que les toca ahora."""
    from app.telegram import TelegramError, enviar_mensaje

    activos = recordatorios_activos()
    toca = [config for config in activos if _le_toca(config)]
    logger.info("Recordatorios: %s activos, %s les toca ahora", len(activos), len(toca))

    enviados = 0
    fallidos = 0
    for config in toca:
        chat_id = int(config["chat_id"])
        try:
            await enviar_mensaje(chat_id, MSG_RECORDATORIO)
        except TelegramError:
            logger.exception("No pude mandarle el recordatorio a %s", chat_id)
            fallidos += 1
            continue

        enviados += 1
        try:
            marcar_recordatorio_enviado(chat_id, _ahora_en(config.get("zona_horaria")).date())
        except DBError:
            logger.warning("Recordatorio enviado a %s pero no pude marcarlo", chat_id)

    return {"activos": len(activos), "enviados": enviados, "fallidos": fallidos}
