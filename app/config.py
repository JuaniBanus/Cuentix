"""Carga y validación de la configuración del proyecto.

Lee el archivo .env de la raíz y expone las variables ya validadas.
Si falta alguna obligatoria, falla al importar el módulo (es decir, al
arrancar la app) con un mensaje que dice exactamente qué hacer.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Raíz del proyecto (un nivel arriba de app/), para que las rutas no
# dependan del directorio desde el que se ejecute uvicorn.
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


TELEGRAM_TOKEN: str = _requerida("TELEGRAM_TOKEN")
GEMINI_API_KEY: str = _requerida("GEMINI_API_KEY")

# Va en la URL del webhook: /webhook/<WEBHOOK_SECRET>. Es lo único que impide
# que cualquiera le mande updates falsos al bot, así que conviene que sea largo
# y aleatorio: python -c "import secrets; print(secrets.token_urlsafe(32))"
WEBHOOK_SECRET: str = _requerida("WEBHOOK_SECRET")

# Base de datos: Supabase (Postgres).
# SUPABASE_KEY debe ser la clave service_role / secret, no la anon: la tabla
# tiene RLS activo sin policies, así que la clave pública no puede tocarla.
SUPABASE_URL: str = _requerida("SUPABASE_URL").rstrip("/")
SUPABASE_KEY: str = _requerida("SUPABASE_KEY")
