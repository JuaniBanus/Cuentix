"""Recordatorio diario: "¿Cómo fue tu día? Contame lo que gastaste."

Dos mitades:

- La configuración, que el usuario fija con /recordatorio desde Telegram.
- El envío, que dispara un cron externo cada hora contra
  POST /tareas/recordatorios/<secreto>.

POR QUÉ UN CRON EXTERNO Y NO UN SCHEDULER ADENTRO
El servicio de Render duerme tras ~15 minutos sin tráfico. Un asyncio.sleep o
un APScheduler dentro del proceso se congelan con él, y a las 21 no hay nadie
despierto para mandar nada. Justo a esa hora, que es cuando el bot no se usó
en todo el día, es cuando más seguro está dormido. El disparo tiene que venir
de afuera. Es el mismo razonamiento que las alertas de precio, y por eso
comparte su secreto y su forma.

POR QUÉ EL CRON CORRE CADA HORA Y NO A LAS 21
Porque la hora la elige cada usuario, y porque el cron de GitHub Actions no es
puntual: en momentos de carga los disparos se retrasan, a veces bastante. Un
cron "a las 21 en punto" que llega 21:40 no manda nada si el código exige que
sean exactamente las 21. Corriendo cada hora y preguntando "¿a quién le toca
en SU zona horaria?", un atraso mueve el aviso pero no lo pierde.

Y por qué se guarda `ultimo_envio`: con disparos que se pueden repetir o
solapar, "es la hora" no alcanza para no mandar dos veces.
"""

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

# /recordatorio · /recordatorio 21 · /recordatorio 21:00 · /recordatorio 9hs
# /recordatorio off · /recordatorio no
_COMANDO = re.compile(
    r"^/recordatorio(?:@\w+)?\s*(?P<resto>.*)$", re.IGNORECASE | re.DOTALL
)
_HORA = re.compile(r"^(?P<hora>\d{1,2})\s*(?::\s*(?P<minutos>\d{2}))?\s*(?:hs?|horas?)?$")
_APAGAR = {"off", "no", "nunca", "apagar", "apagalo", "basta", "cancelar", "0ff"}


def es_comando(texto: str) -> bool:
    return bool(_COMANDO.match((texto or "").strip()))


def atender_comando(chat_id: int, texto: str, user_id: str) -> str:
    """Resuelve /recordatorio y devuelve qué contestarle al usuario.

    `user_id` va porque la fila de `recordatorios` tiene dueño: es lo que hace
    que el recordatorio también aparezca en la web de esa persona, y lo que
    impide que dos usuarios que compartan un chat se pisen la configuración.
    """
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
    """"21", "21:00", "9hs" -> 21, 21, 9. Los minutos se ignoran a propósito.

    El cron corre una vez por hora, así que un "21:30" no se podría cumplir:
    prometer una precisión que no existe es peor que redondear y decirlo.
    """
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
    """¿A este chat le corresponde el aviso en esta corrida?

    Dos condiciones: que en SU zona sea la hora que eligió, y que hoy no se le
    haya mandado ya. La segunda es la que sobrevive a un cron que se repite.
    """
    ahora = _ahora_en(config.get("zona_horaria"))
    if ahora.hour != int(config.get("hora", HORA_POR_DEFECTO)):
        return False
    return config.get("ultimo_envio") != ahora.date().isoformat()


async def enviar_recordatorios() -> dict:
    """Manda el aviso a los chats a los que les toca ahora.

    Cada envío va aislado: si un chat falla —bloqueó al bot, por ejemplo—, los
    demás se mandan igual. Devuelve el conteo para que el cron sepa qué pasó.
    """
    # Importado acá y no arriba: telegram.py importa config, y a nivel de
    # módulo se armaría un ciclo con main.py.
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
            # El aviso ya salió. No poder anotarlo solo arriesga un repetido
            # dentro de la misma hora, que es mejor que no haberlo mandado.
            logger.warning("Recordatorio enviado a %s pero no pude marcarlo", chat_id)

    return {"activos": len(activos), "enviados": enviados, "fallidos": fallidos}
