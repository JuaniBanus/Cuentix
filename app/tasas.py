"""Tasas de referencia para comparar cuotas contra contado."""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

URL_PLAZO_FIJO = "https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo"
URL_INFLACION = "https://api.argentinadatos.com/v1/finanzas/indices/inflacion"

TIEMPO_LIMITE = 8.0
VIGENCIA_CACHE = 6 * 60 * 60

TEM_RESPALDO = Decimal("0.015")
INFLACION_RESPALDO = Decimal("0.020")

_cache: dict[str, tuple[float, "Tasas"]] = {}


class Tasas:
    """Las tasas mensuales que usa la comparación."""

    __slots__ = ("tem_inversion", "inflacion_mensual", "fuente_tasa", "estimadas")

    def __init__(
        self,
        tem_inversion: Decimal,
        inflacion_mensual: Decimal | None,
        fuente_tasa: str,
        estimadas: bool,
    ) -> None:
        self.tem_inversion = tem_inversion
        self.inflacion_mensual = inflacion_mensual
        self.fuente_tasa = fuente_tasa
        self.estimadas = estimadas


def _traer(url: str) -> list | dict:
    with httpx.Client(timeout=TIEMPO_LIMITE, follow_redirects=True) as cliente:
        respuesta = cliente.get(url)
        respuesta.raise_for_status()
        return respuesta.json()


def _mejor_plazo_fijo() -> tuple[Decimal, str] | None:
    """(TEM, banco) del plazo fijo con mejor TNA publicada."""
    try:
        datos = _traer(URL_PLAZO_FIJO)
    except Exception:
        logger.warning("No pude traer las tasas de plazo fijo", exc_info=True)
        return None

    mejor_tna = Decimal("0")
    banco = ""
    for fila in datos if isinstance(datos, list) else []:
        crudo = fila.get("tnaClientes")
        if crudo is None:
            continue
        try:
            tna = Decimal(str(crudo))
        except (InvalidOperation, ValueError):
            continue
        if tna > 3:
            tna = tna / 100
        if tna > mejor_tna:
            mejor_tna, banco = tna, str(fila.get("entidad", "")).title()

    if mejor_tna <= 0:
        return None

    return (mejor_tna / 12).quantize(Decimal("0.00001")), banco


def _inflacion_reciente() -> Decimal | None:
    """Promedio mensual de los últimos tres meses publicados."""
    try:
        datos = _traer(URL_INFLACION)
    except Exception:
        logger.warning("No pude traer la inflación", exc_info=True)
        return None

    valores = []
    for fila in (datos if isinstance(datos, list) else [])[-3:]:
        try:
            valores.append(Decimal(str(fila["valor"])) / 100)
        except (KeyError, InvalidOperation, ValueError, TypeError):
            continue

    if not valores:
        return None
    return (sum(valores) / len(valores)).quantize(Decimal("0.00001"))


def obtener() -> Tasas:
    """Las tasas de referencia, cacheadas seis horas."""
    guardado = _cache.get("tasas")
    if guardado and time.monotonic() - guardado[0] < VIGENCIA_CACHE:
        return guardado[1]

    plazo_fijo = _mejor_plazo_fijo()
    inflacion = _inflacion_reciente()

    if plazo_fijo is not None:
        tem, banco = plazo_fijo
        tasas = Tasas(tem, inflacion, f"plazo fijo {banco}".strip(), estimadas=False)
    else:
        tasas = Tasas(
            TEM_RESPALDO,
            inflacion if inflacion is not None else INFLACION_RESPALDO,
            "estimación propia",
            estimadas=True,
        )

    _cache["tasas"] = (time.monotonic(), tasas)
    return tasas


def limpiar_cache() -> None:
    """Solo para los tests."""
    _cache.clear()
