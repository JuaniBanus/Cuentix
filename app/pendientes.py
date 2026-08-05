"""Preguntas que el bot dejó abiertas y espera que el usuario conteste.

Cuando no se puede imputar un ahorro sin adivinar —porque no hay ningún
objetivo que coincida, o porque coinciden varios—, el bot pregunta. La
respuesta llega en el mensaje siguiente, sin nada que la ate a la pregunta:
Telegram no arrastra contexto. Acá se guarda ese hilo.

Vive en memoria, y eso es una decisión, no un descuido:

- Es una pregunta por chat y dura minutos. Una tabla para eso sería una
  consulta más en cada mensaje del bot, para un dato que se descarta enseguida.
- Si el proceso reinicia (en Render el plan free duerme), la pregunta se
  pierde. El peor caso es que el bot conteste "no te entendí" a un "sí", y el
  MOVIMIENTO YA ESTÁ GUARDADO: lo único que se pierde es la imputación, que se
  puede hacer después desde la web.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Después de diez minutos, un "sí" ya no es la respuesta a esto: es otra cosa.
VIGENCIA_SEGUNDOS = 10 * 60


@dataclass
class Pendiente:
    """La pregunta abierta de un chat.

    `tipo` es "elegir" (varios objetivos coinciden) o "crear" (ninguno).
    `movimiento_id` es el ahorro ya guardado, al que le falta la imputación.
    """

    tipo: str
    movimiento_id: int
    mencion: str
    moneda: str
    candidatos: list[dict] = field(default_factory=list)
    creado: float = field(default_factory=time.monotonic)

    def vencio(self, ahora: float | None = None) -> bool:
        # monotonic y no time(): no lo afecta que se cambie la hora del sistema.
        return (ahora or time.monotonic()) - self.creado > VIGENCIA_SEGUNDOS


_abiertas: dict[int, Pendiente] = {}


def guardar(chat_id: int, pendiente: Pendiente) -> None:
    """Deja una pregunta abierta. Si había otra, la reemplaza."""
    _abiertas[chat_id] = pendiente


def mirar(chat_id: int) -> Pendiente | None:
    """La pregunta abierta del chat, o None. La vencida se descarta sola."""
    pendiente = _abiertas.get(chat_id)
    if pendiente is None:
        return None
    if pendiente.vencio():
        del _abiertas[chat_id]
        return None
    return pendiente


def olvidar(chat_id: int) -> None:
    _abiertas.pop(chat_id, None)


def limpiar() -> None:
    """Solo para los tests."""
    _abiertas.clear()
