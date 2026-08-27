"""Carga y validación de la configuración del proyecto."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria o está vacía."""


def _requerida(nombre: str) -> str:
    """Devuelve la variable `nombre` o corta la ejecución explicando el problema."""
    valor = (os.getenv(nombre) or "").strip()
    if not valor:
        raise ConfigError(
            f"Falta la variable de entorno obligatoria: {nombre}.\n"
            f"Definila en {ENV_FILE} (copiá .env.example a .env y completá el valor) "
            f"o exportala en el entorno antes de arrancar la app."
        )
    return valor


def _opcional(nombre: str) -> str | None:
    """Devuelve la variable `nombre`, o None si no está. No corta nada."""
    return (os.getenv(nombre) or "").strip() or None


def _chat_ids(nombre: str) -> frozenset[int]:
    """Lee una lista de chat_id separados por coma y la devuelve como enteros."""
    ids = set()
    for parte in (_opcional(nombre) or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            ids.add(int(parte))
        except ValueError:
            raise ConfigError(
                f"{nombre} tiene un valor que no es un número: {parte!r}.\n"
                f"Es una lista de chat_id separados por coma, por ejemplo: 123456789"
            ) from None
    return frozenset(ids)


TELEGRAM_TOKEN: str = _requerida("TELEGRAM_TOKEN")
GEMINI_API_KEY: str = _requerida("GEMINI_API_KEY")

WEBHOOK_SECRET: str = _requerida("WEBHOOK_SECRET")

SUPABASE_URL: str = _requerida("SUPABASE_URL").rstrip("/")
SUPABASE_KEY: str = _requerida("SUPABASE_KEY")

CHATS_PERMITIDOS: frozenset[int] = _chat_ids("CHATS_PERMITIDOS")

ALERTAS_SECRET: str | None = _opcional("ALERTAS_SECRET")

TWELVE_DATA_API_KEY: str | None = _opcional("TWELVE_DATA_API_KEY")

ORIGENES_WEB: tuple[str, ...] = tuple(
    origen.strip().rstrip("/")
    for origen in (_opcional("ORIGENES_WEB") or "").split(",")
    if origen.strip()
)
