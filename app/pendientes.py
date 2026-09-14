"""Preguntas que el bot dejó abiertas y espera que el usuario conteste."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

VIGENCIA_SEGUNDOS = 10 * 60

# Cuántas categorías se preguntan como mucho en un mensaje. Un cierre del día
# con veinte ítems raros no puede secuestrar el chat: lo que pasa de acá queda
# en "otros" y se avisa en el resumen.
TOPE_COLA = 5


@dataclass
class Pendiente:
    """La pregunta abierta de un chat.

    Los campos describen la pregunta EN CURSO. `cola` guarda las que vienen
    después, para el caso de un mensaje con varios movimientos sin categoría:
    se contesta una y aparece la siguiente.
    """

    tipo: str
    # Los tres tienen default porque no toda pregunta cuelga de un movimiento:
    # la que confirma lo que se escucho en un audio todavia no anoto nada.
    movimiento_id: int = 0
    mencion: str = ""
    moneda: str = "ARS"
    candidatos: list[dict] = field(default_factory=list)
    cola: list[dict] = field(default_factory=list)
    datos: dict = field(default_factory=dict)
    creado: float = field(default_factory=time.monotonic)

    def vencio(self, ahora: float | None = None) -> bool:
        """El vencimiento corre para la cola entera, no por pregunta.

        Si el usuario se fue a la mitad, lo que quedaba sin contestar se queda
        en "otros" y el próximo mensaje se procesa como cualquier otro.
        """
        return (ahora or time.monotonic()) - self.creado > VIGENCIA_SEGUNDOS

    def avanzar(self) -> bool:
        """Pasa a la siguiente pregunta de la cola. False si no queda ninguna."""
        if not self.cola:
            return False

        siguiente = self.cola.pop(0)
        self.movimiento_id = siguiente["movimiento_id"]
        self.mencion = siguiente["mencion"]
        self.candidatos = siguiente.get("candidatos", [])
        return True

    @property
    def restantes(self) -> int:
        return len(self.cola)


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
