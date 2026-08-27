"""Comprueba que quien llama sea un usuario de la web con la cuenta activa."""

from __future__ import annotations

import logging
import time

import httpx

from app.config import SUPABASE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

_VIGENCIA_CACHE = 300

_MSG_INACTIVA = (
    "Tu cuenta todavía no está habilitada. Pedile a un administrador que la active."
)
_cache: dict[str, tuple[str, str, float]] = {}

_cliente: httpx.AsyncClient | None = None


class SesionInvalida(RuntimeError):
    """El token no es de un usuario válido."""


def _obtener_cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))
    return _cliente


async def cerrar_cliente() -> None:
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


def _limpiar_cache(ahora: float) -> None:
    for token, (_, _estado, vence) in list(_cache.items()):
        if vence <= ahora:
            del _cache[token]


class CuentaInactiva(SesionInvalida):
    """El token es válido pero la cuenta no está activa."""


def _estado_de(user_id: str) -> str:
    """El estado del perfil. Ante un fallo de la base devuelve 'activo'."""
    from app.db import DBError, perfil_de

    try:
        perfil = perfil_de(user_id)
    except DBError as exc:
        logger.warning("No pude leer el estado de %s: %s", user_id, exc)
        return "activo"
    return str((perfil or {}).get("estado") or "pendiente")


async def verificar(cabecera_authorization: str | None, exigir_activo: bool = False) -> str:
    """Devuelve el id del usuario dueño del token, validando la cuenta si se pide."""
    if not cabecera_authorization or not cabecera_authorization.lower().startswith("bearer "):
        raise SesionInvalida("Falta el token de sesión.")

    token = cabecera_authorization[7:].strip()
    if not token:
        raise SesionInvalida("Falta el token de sesión.")

    ahora = time.monotonic()
    _limpiar_cache(ahora)
    if (guardado := _cache.get(token)) and guardado[2] > ahora:
        if exigir_activo and guardado[1] != "activo":
            raise CuentaInactiva(_MSG_INACTIVA)
        return guardado[0]

    try:
        respuesta = await _obtener_cliente().get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        logger.warning("No se pudo validar la sesión contra Supabase: %s", exc)
        raise SesionInvalida("No pude validar tu sesión.") from exc

    if respuesta.status_code != 200:
        raise SesionInvalida("Tu sesión venció. Volvé a entrar.")

    user_id = (respuesta.json() or {}).get("id")
    if not user_id:
        raise SesionInvalida("Tu sesión venció. Volvé a entrar.")

    estado = _estado_de(user_id)
    _cache[token] = (user_id, estado, ahora + _VIGENCIA_CACHE)

    if exigir_activo and estado != "activo":
        raise CuentaInactiva(_MSG_INACTIVA)
    return user_id
