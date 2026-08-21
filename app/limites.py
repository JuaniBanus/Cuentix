"""Límite de pedidos por cliente, en memoria del proceso.

POR QUÉ SIN LIBRERÍA

slowapi y compañía traen un backend de Redis o un estado global que acá no hace
falta: el bot corre en UN solo proceso en Render, y el mismo motivo por el que
el caché de precios vive en un diccionario —ver app/mercado.py— vale para esto.
Una dependencia más es otra cosa que actualizar y otra superficie que auditar.

QUÉ PROTEGE Y QUÉ NO

Protege CUOTA, no datos. Las llamadas a Gemini y al proveedor de precios son
finitas y compartidas: agotarlas no rompe el servidor, hace que el dueño vea
pantallas vacías sin entender por qué. Eso es lo que se está frenando.

No es un anti-DDoS. Si alguien quiere tirar el servicio abajo, el cuello de
botella es Render, no esto. Y como el estado vive en el proceso, un reinicio
perdona a todo el mundo: es aceptable para lo que protege.

LA VENTANA ES DESLIZANTE, NO FIJA

Con ventanas fijas —"N por minuto, se reinicia en el segundo 0"— alguien puede
gastar N al final de un minuto y N al principio del siguiente: 2N pedidos en dos
segundos. Guardar las marcas de tiempo cuesta unos bytes por cliente y elimina
ese borde.
"""

from __future__ import annotations

import time
from collections import deque

# Cuántos clientes distintos se recuerdan. Sin tope, cada IP nueva agrega una
# entrada para siempre y el diccionario se vuelve una fuga de memoria lenta,
# que es justo uno de los hallazgos que este trabajo vino a cerrar.
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

        # Si aun podado sigue por encima del tope, se descartan los más
        # antiguos. Es preferible olvidar a alguien —que en el peor caso
        # consigue un cupo nuevo— antes que crecer sin límite.
        if len(self._marcas) > TOPE_CLIENTES:
            sobran = sorted(self._marcas, key=lambda c: self._marcas[c][-1])
            for cliente in sobran[: len(self._marcas) - TOPE_CLIENTES]:
                del self._marcas[cliente]

    def revisar(self, cliente: str) -> None:
        """Anota un pedido de `cliente`.

        Raises:
            LimiteExcedido: si ya gastó su cupo en la ventana actual.
        """
        ahora = time.monotonic()
        marcas = self._marcas.setdefault(cliente, deque())

        while marcas and ahora - marcas[0] > self.ventana:
            marcas.popleft()

        if len(marcas) >= self.cantidad:
            # Cuándo se libera el lugar más viejo.
            espera = max(1, int(self.ventana - (ahora - marcas[0])) + 1)
            raise LimiteExcedido(espera)

        marcas.append(ahora)
        self._podar(ahora)


def identificar(request) -> str:
    """Con qué clave se cuenta a quien llama.

    Se prefiere la IP que reporta el proxy de Render sobre `request.client`,
    que detrás de un balanceador es siempre la misma para todos y haría que un
    solo abusador consumiera el cupo de todos los demás.

    X-Forwarded-For lo puede escribir cualquiera, así que esto NO sirve para
    identificar a nadie: sirve para repartir el cupo. Quien la falsee consigue
    cupo extra, que es exactamente lo mismo que consigue cambiando de IP.
    """
    reenviada = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if reenviada:
        return reenviada
    return request.client.host if request.client else "desconocido"
