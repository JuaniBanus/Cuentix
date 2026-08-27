"""Límite de pedidos por cliente, en memoria del proceso."""

from __future__ import annotations

import time
from collections import deque

TOPE_CLIENTES = 5_000


class LimiteExcedido(RuntimeError):
    """El cliente superó su cupo. Trae los segundos que faltan para reintentar."""

    def __init__(self, espera: int) -> None:
        super().__init__(f"Demasiados pedidos. Probá de nuevo en {espera} segundos.")
        self.espera = espera


class Limite:
    """Permite `cantidad` pedidos por cada `ventana` segundos y por cliente."""

    def __init__(self, cantidad: int, ventana: float, nombre: str = "") -> None:
        self.cantidad = cantidad
        self.ventana = ventana
        self.nombre = nombre
        self._marcas: dict[str, deque[float]] = {}

    def _podar(self, ahora: float) -> None:
        """Saca a los clientes que ya no tienen marcas vigentes."""
        vacios = [c for c, marcas in self._marcas.items()
                  if not marcas or ahora - marcas[-1] > self.ventana]
        for cliente in vacios:
            del self._marcas[cliente]

        if len(self._marcas) > TOPE_CLIENTES:
            sobran = sorted(self._marcas, key=lambda c: self._marcas[c][-1])
            for cliente in sobran[: len(self._marcas) - TOPE_CLIENTES]:
                del self._marcas[cliente]

    def revisar(self, cliente: str) -> None:
        """Anota un pedido de `cliente`."""
        ahora = time.monotonic()
        marcas = self._marcas.setdefault(cliente, deque())

        while marcas and ahora - marcas[0] > self.ventana:
            marcas.popleft()

        if len(marcas) >= self.cantidad:
            espera = max(1, int(self.ventana - (ahora - marcas[0])) + 1)
            raise LimiteExcedido(espera)

        marcas.append(ahora)
        self._podar(ahora)


def identificar(request) -> str:
    """Con qué clave se cuenta a quien llama."""
    reenviada = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if reenviada:
        return reenviada
    return request.client.host if request.client else "desconocido"
