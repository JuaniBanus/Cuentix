"""Comprueba que quien llama al endpoint de insights sea un usuario de la web."""

from __future__ import annotations

import logging
import time

import httpx

from app.config import SUPABASE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

_VIGENCIA_CACHE = 300
_cache: dict[str, tuple[str, float]] = {}

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
    for token, (_, vence) in list(_cache.items()):
        if vence <= ahora:
            del _cache[token]


async def verificar(cabecera_authorization: str | None) -> str:
    """Devuelve el id del usuario dueño del token."""
    if not cabecera_authorization or not cabecera_authorization.lower().startswith("bearer "):
        raise SesionInvalida("Falta el token de sesión.")

    token = cabecera_authorization[7:].strip()
    if not token:
        raise SesionInvalida("Falta el token de sesión.")

    ahora = time.monotonic()
    _limpiar_cache(ahora)
    if (guardado := _cache.get(token)) and guardado[1] > ahora:
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

    _cache[token] = (user_id, ahora + _VIGENCIA_CACHE)
    return user_id
