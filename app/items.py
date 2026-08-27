"""Identificar «el mismo ítem» entre compras distintas."""

from __future__ import annotations

import logging
import unicodedata
from enum import Enum

from app.objetivos import _parecido

logger = logging.getLogger(__name__)

UMBRAL_PARECIDO = 0.82

_VACIAS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "en", "al", "a", "por", "para", "con", "y",
    "compra", "compre", "pago", "pague", "gasto", "gaste", "mi", "me",
})

_SIGNOS = " ¡!¿?.,;:…\"'()[]{}/-_*"


class ClaseItem(str, Enum):
    """Qué se puede medir con las compras de este ítem."""

    SERVICIO = "servicio"
    UNITARIO = "unitario"
    VARIABLE = "variable"


_CATEGORIAS_SERVICIO = frozenset({
    "servicios", "alquiler", "expensas", "internet", "telefono", "celular",
    "luz", "gas", "agua", "cable", "streaming", "gimnasio", "prepaga",
    "obra social", "seguro", "impuestos", "educacion", "colegio", "cochera",
})

_CATEGORIAS_UNITARIAS = frozenset({
    "transporte", "nafta", "combustible", "carniceria", "verduleria",
})


def normalizar(texto: str) -> str:
    """"El Coto  " -> "coto". Determinista y sin historial."""
    if not texto:
        return ""

    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    palabras = [p.strip(_SIGNOS) for p in sin_tildes.split()]
    utiles = [p for p in palabras if p and p not in _VACIAS]

    if not utiles:
        utiles = [p for p in palabras if p]

    return " ".join(utiles)[:60]


def clase_de(categoria: str, tiene_precio_unitario: bool) -> ClaseItem:
    """Qué se puede medir con este gasto."""
    cat = normalizar(categoria)
    if cat in _CATEGORIAS_SERVICIO:
        return ClaseItem.SERVICIO
    if tiene_precio_unitario:
        return ClaseItem.UNITARIO
    if cat in _CATEGORIAS_UNITARIAS:
        return ClaseItem.VARIABLE
    return ClaseItem.VARIABLE


def elegir_clave(texto: str, conocidas: list[str]) -> tuple[str, bool]:
    """(clave, era_conocida) para una descripción o comercio."""
    clave = normalizar(texto)
    if not clave:
        return "", False

    palabras = set(clave.split())

    mejor, puntaje = "", 0.0
    for conocida in conocidas:
        propias = set(conocida.split())

        if propias and (propias <= palabras or palabras <= propias):
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
    """La clave definitiva de un movimiento."""
    base = (comercio or "").strip() or descripcion
    clave, _ = elegir_clave(base, conocidas)
    return clave
