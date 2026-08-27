"""Preguntas que el bot dejó abiertas y espera que el usuario conteste."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

VIGENCIA_SEGUNDOS = 10 * 60


@dataclass
class Pendiente:
    """La pregunta abierta de un chat."""

    tipo: str
    movimiento_id: int
    mencion: str
    moneda: str
    candidatos: list[dict] = field(default_factory=list)
    creado: float = field(default_factory=time.monotonic)

    def vencio(self, ahora: float | None = None) -> bool:
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
