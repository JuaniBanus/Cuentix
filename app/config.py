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


def _opcional(nombre: str) -> str | None:
    """Devuelve la variable `nombre`, o None si no está. No corta nada."""
    return (os.getenv(nombre) or "").strip() or None


def _chat_ids(nombre: str) -> frozenset[int]:
    """Lee una lista de chat_id separados por coma y la devuelve como enteros.

    Vacía es válido y significa "sin lista": quién puede usar el bot lo decide
    la tabla `usuarios_telegram`. Un valor que no sea número sí corta, porque
    eso no es una decisión, es un typo que dejaría a alguien afuera en silencio.
    """
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

# Va en la URL del webhook: /webhook/<WEBHOOK_SECRET>. Es lo único que impide
# que cualquiera le mande updates falsos al bot, así que conviene que sea largo
# y aleatorio: python -c "import secrets; print(secrets.token_urlsafe(32))"
WEBHOOK_SECRET: str = _requerida("WEBHOOK_SECRET")

# Base de datos: Supabase (Postgres).
# SUPABASE_KEY debe ser la clave service_role / secret, no la anon: la tabla
# tiene RLS activo sin policies, así que la clave pública no puede tocarla.
SUPABASE_URL: str = _requerida("SUPABASE_URL").rstrip("/")
SUPABASE_KEY: str = _requerida("SUPABASE_KEY")

# Quiénes pueden usar el bot: YA NO SE DECIDE ACÁ.
#
# Ahora la lista de acceso es la tabla `usuarios_telegram`, que además dice de
# QUIÉN es cada chat. Una lista de chat_id en el .env no puede hacer eso: sabe
# quién entra, no a nombre de quién guardar. Ver app/usuarios.py.
#
# Esta variable queda como un cerrojo opcional ADICIONAL, no como el principal:
#
#   vacía (lo normal)  -> manda la tabla, y punto.
#   con chat_ids       -> además de estar en la tabla, hay que estar acá.
#
# La segunda forma sirve para una etapa de prueba, donde se quiere que el bot
# atienda a dos personas aunque la tabla ya tenga diez. Tiene un costo que
# conviene saber: sumar un usuario pasa a ser dos pasos, y olvidarse del
# segundo se ve como un "no tengo tu acceso habilitado" que no se explica
# mirando la base. Por eso el arranque loguea cuál de los dos modos está activo.
CHATS_PERMITIDOS: frozenset[int] = _chat_ids("CHATS_PERMITIDOS")

# Secreto que protege el disparador de las alertas de precio.
#
# Va en la URL (/tareas/alertas/<secreto>), igual que el del webhook: quien lo
# llama es un cron, no una persona logueada, así que no hay sesión que validar.
# Sin él, cualquiera podría hacer correr la revisión todo el tiempo y gastarnos
# la cuota del proveedor de precios.
#
# Generalo con: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Vacío = el endpoint responde 404 y las alertas no se revisan solas.
ALERTAS_SECRET: str | None = _opcional("ALERTAS_SECRET")

# Clave de Twelve Data, para el proxy de precios de mercado.
#
# Va acá y NUNCA en web/js/: el navegador muestra todo lo que carga, así que
# una clave en el front es una clave pública. Ese es el motivo de que exista
# el proxy de app/mercado.py.
#
# Se saca gratis en twelvedata.com. Es opcional: sin ella el proxy sigue
# sirviendo los papeles argentinos (Data912 no pide clave) y responde 503 para
# lo demás, explicando qué falta.
TWELVE_DATA_API_KEY: str | None = _opcional("TWELVE_DATA_API_KEY")

# Desde qué orígenes puede llamar la web al endpoint de insights.
#
# Hace falta porque el front y el bot NO comparten origen: la web es estática y
# vive en el hosting compartido, el bot está en Render. Sin CORS el navegador
# bloquea la llamada antes de que salga.
#
# Es una lista blanca separada por coma, no "*": el endpoint gasta cuota de
# Gemini, así que no conviene que cualquier página de internet pueda invocarlo
# desde el navegador de un usuario logueado.
# Ejemplo: ORIGENES_WEB=https://cuentix.com.ar,http://127.0.0.1:8777
ORIGENES_WEB: tuple[str, ...] = tuple(
    origen.strip().rstrip("/")
    for origen in (_opcional("ORIGENES_WEB") or "").split(",")
    if origen.strip()
)
