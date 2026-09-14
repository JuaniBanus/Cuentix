"""Pasar a texto los audios de Telegram, con Gemini.

Esto NO interpreta nada: deja el audio convertido en la misma cadena que
habría escrito el usuario, y de ahí en adelante el mensaje sigue exactamente
el mismo camino que uno tipeado. Dos llamadas a Gemini en vez de una, pero a
cambio los audios heredan gratis todo lo que ya existe: los comandos, las
respuestas fijas, el vocabulario de categorías y las preguntas pendientes.

La otra mitad del trabajo es admitir que no se entendió. Un audio en la calle
con el monto a medias no puede terminar en un movimiento inventado, así que el
modelo devuelve además qué tan seguro está, y con eso `main` decide si registra
o pregunta.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import NamedTuple

from google.genai import types
from pydantic import BaseModel, ValidationError

from app.parser import ParserError, ServicioNoDisponible, pedirle_a_gemini

logger = logging.getLogger(__name__)

# Más que esto no es «anoté un gasto», es otra cosa: se rechaza antes de bajar
# el archivo y antes de gastar cuota.
TOPE_SEGUNDOS = 120

# Un opus de dos minutos ronda los 250 KB. El tope está holgado para cubrir un
# `audio` adjunto en otro formato, y bien lejos de los 20 MB que es lo máximo
# que deja bajar getFile.
TOPE_BYTES = 8 * 1024 * 1024

# Lo que manda Telegram en una nota de voz es siempre audio/ogg. El resto está
# para los archivos adjuntos. Si llega algo raro igual lo intentamos con
# audio/ogg: equivocarse en el mime es un error recuperable, rechazar un audio
# bueno no.
MIME_POR_DEFECTO = "audio/ogg"

MIMES_CONOCIDOS = frozenset({
    "audio/ogg", "audio/oga", "audio/mpeg", "audio/mp3", "audio/mp4",
    "audio/m4a", "audio/x-m4a", "audio/aac", "audio/wav", "audio/x-wav",
    "audio/flac", "audio/webm",
})


class Confianza(str, Enum):
    """Qué tan seguro está el modelo de lo que escuchó."""

    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class Problema(str, Enum):
    """Por qué un audio no se pudo transcribir."""

    VACIO = "vacio"
    INAUDIBLE = "inaudible"
    NO_ES_PLATA = "no_es_plata"


class AudioMuyLargo(ParserError):
    """El audio pasa TOPE_SEGUNDOS. No se transcribe."""

    def __init__(self, duracion: int) -> None:
        super().__init__(f"El audio dura {duracion}s y el tope es {TOPE_SEGUNDOS}s.")
        self.duracion = duracion


class Transcripcion(NamedTuple):
    """El resultado de escuchar un audio.

    `texto` viene vacío cuando hay `problema`: no hay nada que procesar ni que
    confirmar, solo algo que contarle al usuario.
    """

    texto: str
    confianza: Confianza
    problema: Problema | None
    dudas: tuple[str, ...]

    @property
    def hay_que_confirmar(self) -> bool:
        """Si conviene repetirle al usuario lo que se entendió antes de anotarlo."""
        return self.confianza is not Confianza.ALTA or bool(self.dudas)


class _TranscripcionExtraida(BaseModel):
    texto: str = ""
    confianza: Confianza = Confianza.BAJA
    problema: Problema | None = None
    # Qué parte quedó floja: "el monto", "el comercio". Se le muestran al
    # usuario tal cual, así que el prompt las pide cortas y en español.
    dudas: list[str] = []


INSTRUCCION = """\
Transcribís audios cortos de una app de finanzas personales argentina.

Devolvés EXACTAMENTE lo que la persona dijo, en español rioplatense, sin
corregirle el estilo, sin resumir y sin agregar nada que no haya dicho.

REGLAS DE MONTOS
- Escribí los números como se dijeron: "quince lucas" -> "quince lucas",
  "15 mil" -> "15 mil". No los conviertas ni los redondees.
- Si el monto se escuchó a medias o dudás entre dos cifras, NO elijas una:
  ponelo como lo entendiste y sumá "el monto" a `dudas`.

NO COMPLETES LO QUE NO ESCUCHASTE
Estas transcribiendo, no completando. No agregues nombres de comercios, marcas,
lugares ni fechas que no se hayan dicho, y si dudas entre dos palabras
parecidas no elijas la mas conocida por ser la mas probable.

Eso NO significa descartar el audio: si una palabra suelta no se entiende,
transcribi todo el resto igual y sumá esa parte a `dudas`. Devolver un audio
entero como perdido por una palabra floja es el peor resultado posible.

CONFIANZA
- alta: se entendió todo con claridad.
- media: se entiende la idea pero alguna palabra quedó dudosa.
- baja: hay ruido, la voz se corta o estás adivinando.
Ante la duda, bajá la confianza. Es mucho peor anotar un gasto equivocado que
preguntar de nuevo.

PROBLEMAS (con cualquiera de estos, `texto` va vacío)
- vacio: no se escucha ninguna voz.
- inaudible: hay voz pero no se entiende nada de lo que dice.
- no_es_plata: se entiende perfecto, pero no habla de dinero ni le pregunta
  nada a la app. Es alguien mandando un audio a otra persona por error.

`dudas` son las partes flojas, en español y en dos o tres palabras: "el monto",
"el nombre del comercio", "la fecha". Lista vacía si se entendió todo.
"""


def transcribir(audio: bytes, mime: str = "", duracion: int = 0) -> Transcripcion:
    """Convierte un audio en el texto que el usuario habría escrito.

    `duracion` es la que declara Telegram, en segundos. Se chequea acá y no solo
    en quien llama para que no exista forma de transcribir un audio larguísimo
    por olvidarse el control en algún camino nuevo.
    """
    if duracion > TOPE_SEGUNDOS:
        raise AudioMuyLargo(duracion)

    if not audio:
        raise ParserError("El audio vino vacío, no hay nada que transcribir.")

    if len(audio) > TOPE_BYTES:
        raise ParserError(f"El audio pesa {len(audio)} bytes, más de lo que acepto.")

    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in MIMES_CONOCIDOS:
        # Rechazarlo sería peor: Telegram a veces manda el mime vacío, y el
        # modelo suele arreglárselas igual con el contenido real.
        logger.info("Mime de audio desconocido (%r), lo intento como ogg", mime)
        mime = MIME_POR_DEFECTO

    config = types.GenerateContentConfig(
        system_instruction=INSTRUCCION,
        response_mime_type="application/json",
        response_schema=_TranscripcionExtraida,
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
    )

    respuesta = pedirle_a_gemini(
        [types.Part.from_bytes(data=audio, mime_type=mime)], config
    )

    extraida = respuesta.parsed
    if extraida is None:
        crudo = (respuesta.text or "").strip()
        logger.warning("Gemini no devolvió una transcripción parseable: %r", crudo[:300])
        raise ParserError("No pude entender el audio.")

    return _a_transcripcion(extraida)


def _a_transcripcion(extraida: _TranscripcionExtraida) -> Transcripcion:
    """Normaliza lo que contestó el modelo y arregla las combinaciones imposibles."""
    texto = " ".join((extraida.texto or "").split()).strip()

    dudas = tuple(
        limpia
        for duda in (extraida.dudas or [])
        if (limpia := " ".join(str(duda).split()).strip())
    )[:3]

    problema = extraida.problema

    # Un texto vacío sin problema declarado es un problema igual: sin esto, el
    # bot mandaría a interpretar la cadena vacía y contestaría «no entendí»,
    # que para un audio es una respuesta confusa.
    if not texto and problema is None:
        problema = Problema.INAUDIBLE

    # Y al revés: si declaró un problema, lo que haya transcripto no se usa.
    if problema is not None:
        return Transcripcion("", Confianza.BAJA, problema, ())

    return Transcripcion(texto, extraida.confianza, None, dudas)
