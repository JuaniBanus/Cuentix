"""Tasas de referencia para comparar cuotas contra contado.

De dónde salen y por qué esas:

- PLAZO FIJO (api.argentinadatos.com): es el costo de oportunidad concreto de
  gastar la plata hoy. Si no la usás para pagar al contado, esto es lo que
  rinde sin riesgo ni gestión. Se toma la TNA más alta publicada, porque es la
  que cualquiera puede conseguir buscando un rato.

- INFLACIÓN (misma fuente, serie del INDEC): NO se usa para decidir, se usa
  para dar contexto. La confusión es común y vale aclararla: para elegir entre
  dos formas de pagar LO MISMO, lo que importa es cuánto rinde la plata que no
  gastás, no cuánto sube el nivel general de precios. La inflación entra en la
  decisión indirectamente, porque es la que empuja las tasas.

Las dos son gratuitas y sin clave. Si alguna no responde, se usa un valor de
respaldo y el mensaje al usuario lo dice: preferimos contestar con un número
viejo y avisarlo antes que no contestar.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

URL_PLAZO_FIJO = "https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo"
URL_INFLACION = "https://api.argentinadatos.com/v1/finanzas/indices/inflacion"

TIEMPO_LIMITE = 8.0
VIGENCIA_CACHE = 6 * 60 * 60  # las tasas se mueven de a días, no de a minutos

# Respaldos, por si las dos APIs están caídas. Son órdenes de magnitud
# plausibles, no valores vigentes, y por eso el texto avisa cuando se usan.
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
        # Tasa efectiva MENSUAL de lo que rinde la plata sin riesgo.
        self.tem_inversion = tem_inversion
        self.inflacion_mensual = inflacion_mensual
        self.fuente_tasa = fuente_tasa
        # True = no se pudo consultar y son valores de respaldo.
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
        # La API publica la TNA como fracción (0.19 = 19%). Si algún día
        # cambiara a porcentaje, un 19 se leería como 1900% anual: se acota.
        if tna > 3:
            tna = tna / 100
        if tna > mejor_tna:
            mejor_tna, banco = tna, str(fila.get("entidad", "")).title()

    if mejor_tna <= 0:
        return None

    # TNA a mensual: la TNA es nominal anual con capitalización a 30 días, así
    # que el mes es TNA/12. No es (1+TNA)^(1/12), que sería pasar de efectiva.
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
    # Promedio simple de tres meses: alcanza para contextualizar y no se
    # deforma con un mes suelto.
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
