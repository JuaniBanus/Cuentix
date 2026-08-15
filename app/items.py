"""Identificar «el mismo ítem» entre compras distintas.

El problema: la misma compra aparece como "coto", "el coto" o "compra en el
coto". Agrupar por el texto tal cual fragmentaría el historial justo donde
hace falta que sea continuo para poder comparar precios.

TRES CAPAS, DE MÁS BARATA A MÁS CARA

1. Normalización determinista: minúsculas, sin tildes, sin artículos ni
   preposiciones, espacios colapsados. "El Coto" -> "coto". Es pura función:
   la misma entrada da siempre la misma salida, sin depender del historial.

2. Coincidencia difusa contra las claves que el usuario YA tiene. "edesur" y
   "edesur luz" son lo mismo. Se reutiliza `_parecido` de app/objetivos.py:
   el proyecto ya resolvió este problema para los objetivos de ahorro y tener
   dos mecanismos parecidos que se comportan distinto sería peor que el bug
   que arreglan.

3. Persistencia: la clave se guarda en la fila. No se recalcula al consultar,
   porque el mismo algoritmo agrupa distinto a medida que crece el historial,
   y el termómetro cambiaría de números sin que nadie toque nada.

QUÉ SE PUEDE COMPARAR Y QUÉ NO

No todo gasto repetido sirve para medir inflación:

- SERVICIO: luz, internet, alquiler. El total ES el precio. Comparable.
- UNITARIO: nafta, carne. Comparable SOLO si se capturó el precio por unidad.
- VARIABLE: súper, comida, ropa. El total es precio × cantidad, y sin la
  cantidad no hay forma de separarlos. NO comparable.

Meter la tercera clase en un índice de inflación produciría un número que
parece serio y no lo es: diría "el súper subió 30%" cuando lo que pasó es que
compraste para un asado.
"""

from __future__ import annotations

import logging
import unicodedata
from enum import Enum

from app.objetivos import _parecido

logger = logging.getLogger(__name__)

# Con menos que esto, "nafta" y "farmacia" empiezan a parecerse.
UMBRAL_PARECIDO = 0.82

# Palabras que no distinguen un ítem de otro.
_VACIAS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "en", "al", "a", "por", "para", "con", "y",
    "compra", "compre", "pago", "pague", "gasto", "gaste", "mi", "me",
})

_SIGNOS = " ¡!¿?.,;:…\"'()[]{}/-_*"


class ClaseItem(str, Enum):
    """Qué se puede medir con las compras de este ítem."""

    SERVICIO = "servicio"    # el total es el precio: comparable directo
    UNITARIO = "unitario"    # comparable si hay precio por unidad
    VARIABLE = "variable"    # el total mezcla precio y cantidad: no comparable


# Categorías donde el total del movimiento ES el precio del servicio. Son las
# que se pagan una vez por período por lo mismo.
_CATEGORIAS_SERVICIO = frozenset({
    "servicios", "alquiler", "expensas", "internet", "telefono", "celular",
    "luz", "gas", "agua", "cable", "streaming", "gimnasio", "prepaga",
    "obra social", "seguro", "impuestos", "educacion", "colegio", "cochera",
})

# Categorías que se compran por unidad y donde el precio unitario tiene
# sentido, si el usuario lo menciona.
_CATEGORIAS_UNITARIAS = frozenset({
    "transporte", "nafta", "combustible", "carniceria", "verduleria",
})


def normalizar(texto: str) -> str:
    """"El Coto  " -> "coto". Determinista y sin historial."""
    if not texto:
        return ""

    # NFD separa la letra de su tilde y "Mn" es esa tilde suelta: sacándola
    # queda la letra pelada, y "peluquería" y "peluqueria" caen en la misma.
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    palabras = [p.strip(_SIGNOS) for p in sin_tildes.split()]
    utiles = [p for p in palabras if p and p not in _VACIAS]

    # Si al sacar las vacías no queda nada ("compra de la"), se prefiere el
    # texto pelado antes que una clave vacía que agruparía todo junto.
    if not utiles:
        utiles = [p for p in palabras if p]

    return " ".join(utiles)[:60]


def clase_de(categoria: str, tiene_precio_unitario: bool) -> ClaseItem:
    """Qué se puede medir con este gasto."""
    cat = normalizar(categoria)
    if cat in _CATEGORIAS_SERVICIO:
        return ClaseItem.SERVICIO
    if tiene_precio_unitario:
        # Con precio por unidad, cualquier rubro es comparable: es justamente
        # el dato que separa el precio de la cantidad.
        return ClaseItem.UNITARIO
    if cat in _CATEGORIAS_UNITARIAS:
        # Es unitario por naturaleza pero no se capturó la unidad: entra como
        # variable, porque comparar totales de nafta no dice nada del litro.
        return ClaseItem.VARIABLE
    return ClaseItem.VARIABLE


def elegir_clave(texto: str, conocidas: list[str]) -> tuple[str, bool]:
    """(clave, era_conocida) para una descripción o comercio.

    Si se parece lo suficiente a una clave que el usuario ya usó, se reutiliza
    ESA: mantener el historial junto vale más que la precisión del nombre.
    """
    clave = normalizar(texto)
    if not clave:
        return "", False

    palabras = set(clave.split())

    mejor, puntaje = "", 0.0
    for conocida in conocidas:
        propias = set(conocida.split())

        # Contención de palabras antes que parecido de letras: "edesur luz" y
        # "edesur" son el mismo servicio, pero como cadenas se parecen solo un
        # 0,75 y el umbral difuso las separaría. Bajar el umbral para que
        # entren haría que también entren cosas que no tienen nada que ver;
        # exigir que una contenga a la otra es preciso y no arrastra ruido.
        if propias and (propias <= palabras or palabras <= propias):
            # Gana la más corta: es la raíz común y la que ya agrupa historial.
            return (conocida if len(propias) <= len(palabras) else clave), True

        actual = _parecido(clave, conocida)
        if actual > puntaje:
            mejor, puntaje = conocida, actual

    if puntaje >= UMBRAL_PARECIDO:
        if mejor != clave:
            logger.info("Ítem %r agrupado con %r (parecido %.2f)", clave, mejor, puntaje)
        return mejor, True

    return clave, False


def clave_para(
    *, descripcion: str, comercio: str | None, conocidas: list[str]
) -> str:
    """La clave definitiva de un movimiento.

    El comercio manda sobre la descripción cuando está: "coto" identifica mejor
    una compra repetida que "compra grande del mes", que cambia cada vez.
    """
    base = (comercio or "").strip() or descripcion
    clave, _ = elegir_clave(base, conocidas)
    return clave
