"""Quién escribe: del chat_id de Telegram al user_id de Supabase."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.db import DBError, perfil_de, vinculo_de_chat

logger = logging.getLogger(__name__)

VIGENCIA_CACHE = 60.0

ESTADO_HABILITADO = "activo"


@dataclass(frozen=True)
class Usuario:
    """El dueño de un chat, ya resuelto y con su estado de cuenta."""

    chat_id: int
    user_id: str
    email: str
    estado: str

    @property
    def habilitado(self) -> bool:
        """Solo 'activo' puede usar el bot."""
        return self.estado == ESTADO_HABILITADO


_cache: dict[int, tuple[float, Usuario | None]] = {}


def resolver(chat_id: int) -> Usuario | None:
    """El usuario dueño de ese chat, o None si no lo hay o no se pudo saber."""
    ahora = time.monotonic()

    guardado = _cache.get(chat_id)
    if guardado is not None and ahora - guardado[0] < VIGENCIA_CACHE:
        return guardado[1]

    usuario = _consultar(chat_id)
    _cache[chat_id] = (ahora, usuario)
    return usuario


def _consultar(chat_id: int) -> Usuario | None:
    """Las dos consultas: el vínculo y después el perfil."""
    try:
        vinculo = vinculo_de_chat(chat_id)
    except DBError:
        logger.exception("No pude resolver el chat %s contra usuarios_telegram", chat_id)
        return None

    if vinculo is None:
        logger.warning("Chat %s sin vincular: no hay fila en usuarios_telegram", chat_id)
        return None

    user_id = str(vinculo.get("user_id") or "")
    if not user_id:
        logger.error("El vínculo del chat %s no tiene user_id", chat_id)
        return None

    try:
        perfil = perfil_de(user_id)
    except DBError:
        logger.exception("No pude leer el perfil de %s", user_id)
        return None

    if perfil is None:
        logger.error("El usuario %s del chat %s no tiene perfil", user_id, chat_id)
        return None

    usuario = Usuario(
        chat_id=chat_id,
        user_id=user_id,
        email=str(perfil.get("email") or ""),
        estado=str(perfil.get("estado") or ""),
    )

    if not usuario.habilitado:
        logger.warning(
            "Chat %s vinculado a %s, pero la cuenta está %r",
            chat_id, usuario.email, usuario.estado,
        )

    return usuario


def olvidar(chat_id: int) -> None:
    """Descarta lo cacheado de un chat, para que el próximo mensaje relea."""
    _cache.pop(chat_id, None)


def limpiar() -> None:
    """Vacía el caché entero. Solo para los tests."""
    _cache.clear()
