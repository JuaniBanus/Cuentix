"""Emparejar lo que dijo el usuario con un objetivo de ahorro suyo."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

_VACIAS = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "para", "por", "a", "al", "en", "con",
        "mi", "mis", "tu", "tus", "que", "y", "o",
    }
)

_SIGNOS = re.compile(r"[^\w\s]", re.UNICODE)

_PISO_TOKENS = 0.6
_PISO_LETRAS = 0.8
_PREFIJO_MINIMO = 4
_CONTENIDO_MINIMO = 4


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, sin signos y con los espacios colapsados."""
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(_SIGNOS.sub(" ", sin_tildes).split())


def _significativas(texto: str) -> set[str]:
    return {p for p in normalizar(texto).split() if p not in _VACIAS}


def _parecido(a: str, b: str) -> float:
    """Parecido letra a letra, 0 a 1. Para aguantar un typo, no para adivinar."""
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()


def _misma_raiz(a: str, b: str) -> bool:
    """¿Dos palabras arrancan igual y por bastante?"""
    if len(a) < _PREFIJO_MINIMO or len(b) < _PREFIJO_MINIMO:
        return False

    comunes = 0
    for letra_a, letra_b in zip(a, b):
        if letra_a != letra_b:
            break
        comunes += 1

    return comunes >= _PREFIJO_MINIMO and comunes / min(len(a), len(b)) >= _PISO_TOKENS


@dataclass
class Coincidencias:
    """El mejor nivel de coincidencia que se encontró, y con qué objetivos."""

    objetivos: list[dict] = field(default_factory=list)

    @property
    def unico(self) -> dict | None:
        return self.objetivos[0] if len(self.objetivos) == 1 else None

    @property
    def hay_varios(self) -> bool:
        return len(self.objetivos) > 1

    def __bool__(self) -> bool:
        return bool(self.objetivos)


def buscar(mencion: str, objetivos: list[dict]) -> Coincidencias:
    """Los objetivos que coinciden con lo que dijo el usuario."""
    mencion_norm = normalizar(mencion)
    if not mencion_norm or not objetivos:
        return Coincidencias()

    tokens_mencion = _significativas(mencion)

    exactos, contenidos, por_tokens, por_letras, por_raiz = [], [], [], [], []

    for objetivo in objetivos:
        nombre = normalizar(objetivo.get("nombre", ""))
        if not nombre:
            continue

        if nombre == mencion_norm:
            exactos.append(objetivo)
            continue

        if (
            min(len(nombre), len(mencion_norm)) >= _CONTENIDO_MINIMO
            and (nombre in mencion_norm or mencion_norm in nombre)
        ):
            contenidos.append(objetivo)
            continue

        tokens_nombre = _significativas(nombre)
        compartidas = tokens_mencion & tokens_nombre
        if compartidas and tokens_mencion and tokens_nombre:
            proporcion = len(compartidas) / min(len(tokens_mencion), len(tokens_nombre))
            if proporcion >= _PISO_TOKENS:
                por_tokens.append(objetivo)
                continue

        if _parecido(mencion_norm, nombre) >= _PISO_LETRAS:
            por_letras.append(objetivo)
            continue

        con_raiz = sum(
            1
            for palabra in tokens_mencion
            if any(_misma_raiz(palabra, otra) for otra in tokens_nombre)
        )
        if con_raiz and tokens_mencion and tokens_nombre:
            proporcion = con_raiz / min(len(tokens_mencion), len(tokens_nombre))
            if proporcion >= _PISO_TOKENS:
                por_raiz.append(objetivo)

    for nivel in (exactos, contenidos, por_tokens, por_letras, por_raiz):
        if nivel:
            return Coincidencias(nivel)
    return Coincidencias()


_MULTIPLICADORES = {
    "luca": 1_000, "lucas": 1_000,
    "mil": 1_000, "k": 1_000,
    "palo": 1_000_000, "palos": 1_000_000,
    "millon": 1_000_000, "millones": 1_000_000,
    "gamba": 100, "gambas": 100,
}

_NUMERO = re.compile(r"(-?)(\d[\d.,]*)")

_LIMPIEZA_MONTO = re.compile(r"[^\w\s.,-]", re.UNICODE)


def _normalizar_monto(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(_LIMPIEZA_MONTO.sub(" ", sin_tildes).split())


def _a_decimal(crudo: str) -> Decimal | None:
    """Lee un número en formato argentino: el punto separa miles, la coma decimales."""
    limpio = crudo.rstrip(".,").replace(".", "").replace(",", ".")
    try:
        return Decimal(limpio)
    except InvalidOperation:
        return None


def parsear_monto(texto: str) -> Decimal | None:
    """El monto que dice el texto, o None si no hay uno claro."""
    normal = _normalizar_monto(texto)
    if not normal:
        return None

    encontrado = _NUMERO.search(normal)

    if encontrado:
        if encontrado.group(1) == "-":
            return None
        cantidad = _a_decimal(encontrado.group(2))
        if cantidad is None:
            return None
        resto = normal[encontrado.end():].split()
    else:
        palabras = normal.split()
        if palabras and palabras[0] in {"un", "una"}:
            cantidad, resto = Decimal(1), palabras[1:]
        elif palabras and palabras[0] == "medio":
            cantidad, resto = Decimal("0.5"), palabras[1:]
        else:
            return None

    if resto and resto[0] in _MULTIPLICADORES:
        cantidad *= _MULTIPLICADORES[resto[0]]

    cantidad = cantidad.quantize(Decimal("0.01"))
    return cantidad if cantidad > 0 else None


def progreso(aportado: Decimal, meta: Decimal) -> tuple[int, Decimal, bool]:
    """(porcentaje, cuánto falta, si está completo)."""
    if meta <= 0:
        return 0, Decimal("0"), False
    porcentaje = int((aportado / meta) * 100)
    return porcentaje, max(meta - aportado, Decimal("0")), aportado >= meta
