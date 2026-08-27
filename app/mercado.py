"""Proxy de precios de mercado: acciones, CEDEARs e índices."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import TWELVE_DATA_API_KEY

logger = logging.getLogger(__name__)

URL_TWELVE = "https://api.twelvedata.com"
URL_DATA912 = "https://data912.com"

TTL_SEGUNDOS = 30 * 60
TTL_CERRADO = 6 * 60 * 60

TOPE_DIARIO = 700
TOPE_POR_MINUTO = 6

TIEMPO_LIMITE = 10.0

LISTAS_ARG = ("arg_stocks", "arg_cedears", "arg_bonds")

TICKER_VALIDO = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")

TOPE_CACHE = 500


class MercadoError(RuntimeError):
    """No se pudo obtener el precio."""


class SinClave(MercadoError):
    """Falta configurar TWELVE_DATA_API_KEY."""


class ValorInvalido(MercadoError):
    """El pedido está mal armado. Es culpa de quien llama, no del proveedor."""


_cache: dict[str, tuple[Any, float, float]] = {}
_cliente: httpx.AsyncClient | None = None

_gastadas = 0
_dia_utc = ""
_recientes: list[float] = []


def _obtener_cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = httpx.AsyncClient(timeout=httpx.Timeout(TIEMPO_LIMITE, connect=4.0))
    return _cliente


async def cerrar_cliente() -> None:
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


def _hoy_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def presupuesto() -> dict[str, Any]:
    """Cuánto queda del cupo diario. Se expone para poder monitorearlo."""
    global _gastadas, _dia_utc
    if _dia_utc != _hoy_utc():
        _gastadas, _dia_utc = 0, _hoy_utc()
    return {"gastadas": _gastadas, "tope": TOPE_DIARIO, "restantes": max(0, TOPE_DIARIO - _gastadas)}


def _hay_cupo() -> bool:
    if presupuesto()["restantes"] <= 0:
        return False
    ahora = time.monotonic()
    _recientes[:] = [t for t in _recientes if ahora - t < 60]
    return len(_recientes) < TOPE_POR_MINUTO


def _anotar_llamada() -> None:
    global _gastadas
    presupuesto()
    _gastadas += 1
    _recientes.append(time.monotonic())


def _guardado(clave: str) -> tuple[Any, bool] | None:
    """(dato, vencido) o None si nunca se pidió."""
    if clave not in _cache:
        return None
    dato, momento, ttl = _cache[clave]
    return dato, (time.monotonic() - momento) > ttl


def _guardar(clave: str, dato: Any, ttl: float | None = None) -> None:
    _cache.pop(clave, None)
    if ttl is None:
        abierto = dato.get("abierto") if isinstance(dato, dict) else None
        ttl = TTL_SEGUNDOS if abierto is not False else TTL_CERRADO
    _cache[clave] = (dato, time.monotonic(), ttl)

    if len(_cache) > TOPE_CACHE:
        for vieja in list(_cache)[: len(_cache) - TOPE_CACHE]:
            del _cache[vieja]


def _limpiar_ticker(ticker: str) -> str:
    """Normaliza y valida un ticker, o explica por qué no sirve."""
    limpio = (ticker or "").strip().upper()
    if not limpio:
        raise ValorInvalido("Falta el ticker.")
    if not TICKER_VALIDO.match(limpio):
        raise ValorInvalido(
            "Ticker inválido: se admiten letras, números, punto y guion "
            "(hasta 20 caracteres)."
        )
    return limpio


def _limpiar_mercado(mercado: str | None) -> str:
    elegido = (mercado or "us").strip().lower()
    if elegido not in ("us", "ar"):
        raise ValorInvalido("El mercado tiene que ser «us» o «ar».")
    return elegido


async def _pedir_twelve(ruta: str, params: dict) -> dict:
    if not TWELVE_DATA_API_KEY:
        raise SinClave(
            "Falta TWELVE_DATA_API_KEY. Sacala gratis en twelvedata.com y ponela "
            "en el .env del servidor (nunca en el código de la web)."
        )

    _anotar_llamada()
    try:
        respuesta = await _obtener_cliente().get(
            f"{URL_TWELVE}/{ruta}", params={**params, "apikey": TWELVE_DATA_API_KEY}
        )
    except httpx.HTTPError as exc:
        raise MercadoError("No pude comunicarme con el proveedor de precios.") from exc

    datos = respuesta.json()
    if isinstance(datos, dict) and datos.get("code") and int(datos["code"]) >= 400:
        mensaje = str(datos.get("message", ""))
        if int(datos["code"]) == 429:
            raise MercadoError("Se agotó la cuota de consultas por hoy.")
        raise MercadoError(f"El proveedor rechazó la consulta: {mensaje[:120]}")

    return datos


def _numero(valor: Any) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


def _redondear(valor: float | None) -> float | None:
    """Dos decimales. El proveedor manda cosas como 0.3778135, y siete"""
    return None if valor is None else round(valor, 2)


def _variacion(actual: float | None, anterior: float | None) -> float | None:
    if actual is None or not anterior:
        return None
    return round((actual - anterior) / anterior * 100, 2)


async def _serie(simbolo: str) -> list[dict]:
    """Cierres diarios, del más reciente al más viejo. Para semana y mes."""
    datos = await _pedir_twelve(
        "time_series", {"symbol": simbolo, "interval": "1day", "outputsize": "35"}
    )
    return datos.get("values") or []


def _cierre_hace(serie: list[dict], ruedas: int) -> float | None:
    """El cierre de hace N ruedas. Cuenta ruedas y no días de calendario: una"""
    if len(serie) <= ruedas:
        return None
    return _numero(serie[ruedas].get("close"))


async def _armar(simbolo: str, etiqueta: str) -> dict:
    """Precio y variaciones de un símbolo. Dos llamadas: quote y time_series."""
    quote = await _pedir_twelve("quote", {"symbol": simbolo})

    precio = _numero(quote.get("close"))
    if precio is None:
        raise MercadoError(f"No encontré datos para «{etiqueta}».")

    serie = await _serie(simbolo)
    cincuenta_dos = quote.get("fifty_two_week") or {}

    return {
        "simbolo": quote.get("symbol") or simbolo,
        "nombre": quote.get("name"),
        "precio": precio,
        "moneda": quote.get("currency"),
        "mercado": quote.get("exchange"),
        "variacion": {
            "dia": _redondear(_numero(quote.get("percent_change"))),
            "semana": _variacion(precio, _cierre_hace(serie, 5)),
            "mes": _variacion(precio, _cierre_hace(serie, 21)),
        },
        "rango_dia": {"min": _numero(quote.get("low")), "max": _numero(quote.get("high"))},
        "rango_52_semanas": {
            "min": _numero(cincuenta_dos.get("low")),
            "max": _numero(cincuenta_dos.get("high")),
        },
        "actualizado": quote.get("datetime"),
        "abierto": quote.get("is_market_open"),
        "fuente": "twelvedata",
    }


async def _rueda_argentina(lista: str) -> list[dict]:
    """Una lista entera de Data912, cacheada como bloque."""
    clave = f"arg:{lista}"
    if (previo := _guardado(clave)) and not previo[1]:
        return previo[0]

    try:
        respuesta = await _obtener_cliente().get(f"{URL_DATA912}/live/{lista}")
        respuesta.raise_for_status()
        filas = respuesta.json()
    except (httpx.HTTPError, ValueError) as exc:
        if previo:
            return previo[0]
        raise MercadoError("No pude traer la rueda argentina.") from exc

    _guardar(clave, filas)
    return filas


async def _buscar_argentino(ticker: str) -> dict | None:
    """Busca el ticker en las listas argentinas. None si no está en ninguna."""
    for lista in LISTAS_ARG:
        try:
            filas = await _rueda_argentina(lista)
        except MercadoError:
            continue
        for fila in filas:
            if str(fila.get("symbol", "")).upper() == ticker:
                return {
                    "simbolo": ticker,
                    "nombre": None,
                    "precio": _numero(fila.get("c")),
                    "moneda": "ARS",
                    "mercado": "BYMA",
                    "variacion": {"dia": _numero(fila.get("pct_change")), "semana": None, "mes": None},
                    "rango_dia": {"min": None, "max": None},
                    "rango_52_semanas": {"min": None, "max": None},
                    "actualizado": None,
                    "fuente": f"data912:{lista}",
                }
    return None


async def precio(ticker: str, mercado: str = "us") -> dict:
    """Precio y variaciones de una acción o CEDEAR."""
    ticker = _limpiar_ticker(ticker)
    mercado = _limpiar_mercado(mercado)

    clave = f"precio:{mercado}:{ticker}"
    guardado = _guardado(clave)
    if guardado and not guardado[1]:
        return {**guardado[0], "cacheado": True, "vencido": False}

    if mercado == "ar":
        arg = await _buscar_argentino(ticker)
        if arg is None:
            raise MercadoError(f"No encontré «{ticker}» en el mercado argentino.")
        _guardar(clave, arg)
        return {**arg, "cacheado": False, "vencido": False}

    if not _hay_cupo():
        if guardado:
            logger.info("Sin cupo: se devuelve %s vencido", ticker)
            return {**guardado[0], "cacheado": True, "vencido": True}
        raise MercadoError("Se alcanzó el límite de consultas por ahora. Probá en un minuto.")

    try:
        datos = await _armar(ticker, ticker)
    except MercadoError:
        if guardado:
            return {**guardado[0], "cacheado": True, "vencido": True}
        raise

    _guardar(clave, datos)
    return {**datos, "cacheado": False, "vencido": False}


async def historico(ticker: str, mercado: str = "us", dias: int = 90) -> dict:
    """Serie de cierres diarios, del más viejo al más nuevo, para graficar."""
    ticker = _limpiar_ticker(ticker)
    mercado = _limpiar_mercado(mercado)

    try:
        dias = max(7, min(int(dias or 90), 365))
    except (TypeError, ValueError) as exc:
        raise ValorInvalido("«dias» tiene que ser un número entero.") from exc

    clave = f"hist:{mercado}:{ticker}:{dias}"
    guardado = _guardado(clave)
    if guardado and not guardado[1]:
        return {**guardado[0], "cacheado": True, "vencido": False}

    if mercado == "ar":
        datos = await _historico_argentino(ticker, dias)
    else:
        if not _hay_cupo():
            if guardado:
                return {**guardado[0], "cacheado": True, "vencido": True}
            raise MercadoError("Se alcanzó el límite de consultas por ahora.")
        crudo = await _pedir_twelve(
            "time_series", {"symbol": ticker, "interval": "1day", "outputsize": str(dias)}
        )
        valores = crudo.get("values") or []
        if not valores:
            raise MercadoError(f"No hay histórico para «{ticker}».")
        datos = {
            "simbolo": ticker,
            "moneda": (crudo.get("meta") or {}).get("currency"),
            "puntos": [
                {"fecha": v.get("datetime"), "cierre": _numero(v.get("close"))}
                for v in reversed(valores)
                if _numero(v.get("close")) is not None
            ],
            "fuente": "twelvedata",
        }

    _guardar(clave, datos)
    return {**datos, "cacheado": False, "vencido": False}


async def _historico_argentino(ticker: str, dias: int) -> dict:
    """Data912 tiene histórico por ticker, separado por tipo de instrumento."""
    for tipo in ("stocks", "cedears", "bonds"):
        try:
            respuesta = await _obtener_cliente().get(
                f"{URL_DATA912}/historical/{tipo}/{ticker}"
            )
            if respuesta.status_code != 200:
                continue
            filas = respuesta.json()
        except (httpx.HTTPError, ValueError):
            continue

        if not isinstance(filas, list) or not filas:
            continue

        puntos = []
        for fila in filas[-dias:]:
            cierre = _numero(fila.get("c") if "c" in fila else fila.get("close"))
            fecha = fila.get("date") or fila.get("fecha") or fila.get("datetime")
            if cierre is not None and fecha:
                puntos.append({"fecha": str(fecha)[:10], "cierre": cierre})

        if puntos:
            puntos.sort(key=lambda p: p["fecha"])
            return {
                "simbolo": ticker,
                "moneda": "ARS",
                "puntos": puntos,
                "fuente": f"data912:{tipo}",
            }

    raise MercadoError(f"No hay histórico argentino para «{ticker}».")


INDICES = {
    "^GSPC": {"simbolo": "GSPC", "nombre": "S&P 500"},
    "GSPC": {"simbolo": "GSPC", "nombre": "S&P 500"},
    "SPX": {"simbolo": "GSPC", "nombre": "S&P 500"},
    "^MERV": {"simbolo": "MERV", "nombre": "Merval"},
    "MERV": {"simbolo": "MERV", "nombre": "Merval"},
}


async def indice(symbol: str) -> dict:
    """Valor de un índice bursátil."""
    pedido = symbol.strip().upper()
    conocido = INDICES.get(pedido)
    if not conocido:
        raise ValorInvalido(
            f"No conozco el índice «{symbol}». Por ahora: {', '.join(sorted(set(INDICES)))}."
        )

    clave = f"indice:{conocido['simbolo']}"
    guardado = _guardado(clave)
    if guardado and not guardado[1]:
        return {**guardado[0], "cacheado": True, "vencido": False}

    if not _hay_cupo():
        if guardado:
            return {**guardado[0], "cacheado": True, "vencido": True}
        raise MercadoError("Se alcanzó el límite de consultas por ahora. Probá en un minuto.")

    try:
        datos = await _armar(conocido["simbolo"], conocido["nombre"])
    except MercadoError:
        if guardado:
            return {**guardado[0], "cacheado": True, "vencido": True}
        raise

    datos["nombre"] = datos.get("nombre") or conocido["nombre"]
    datos["simbolo"] = pedido
    _guardar(clave, datos)
    return {**datos, "cacheado": False, "vencido": False}


UNIDADES_POR_PRECIO = 2
TOPE_LOTE = 25


def costo(ticker: str, mercado: str = "us") -> int:
    """Cuántas llamadas al proveedor costaría este precio ahora mismo."""
    try:
        ticker = _limpiar_ticker(ticker)
        mercado = _limpiar_mercado(mercado)
    except ValorInvalido:
        return 0
    if mercado == "ar":
        return 0
    guardado = _guardado(f"precio:{mercado}:{ticker}")
    return 0 if (guardado and not guardado[1]) else UNIDADES_POR_PRECIO


def costo_lote(pedidos: list[tuple[str, str]]) -> int:
    """Lo que costaría todo el lote, sin contar lo que ya está fresco en caché."""
    return sum(costo(t, m) for t, m in pedidos)


async def precios(pedidos: list[tuple[str, str]], solo_cache: bool = False) -> dict[str, Any]:
    """Precios de varios activos, en un mapa por «mercado:TICKER».

    Con `solo_cache` no se llama al proveedor: se sirve lo guardado aunque esté
    vencido. Es el modo degradado para cuando el usuario se quedó sin cupo.
    """
    if len(pedidos) > TOPE_LOTE:
        raise ValorInvalido(f"Son demasiados activos de una vez (máximo {TOPE_LOTE}).")

    resultados: dict[str, Any] = {}
    sin_cobertura: list[str] = []

    for crudo_ticker, crudo_mercado in pedidos:
        try:
            ticker = _limpiar_ticker(crudo_ticker)
            mercado = _limpiar_mercado(crudo_mercado)
        except ValorInvalido:
            sin_cobertura.append(str(crudo_ticker))
            continue

        clave = f"{mercado}:{ticker}"
        if solo_cache:
            guardado = _guardado(f"precio:{mercado}:{ticker}")
            if guardado:
                resultados[clave] = {**guardado[0], "cacheado": True, "vencido": guardado[1]}
            else:
                sin_cobertura.append(ticker)
            continue

        try:
            resultados[clave] = await precio(ticker, mercado)
        except ValorInvalido:
            sin_cobertura.append(ticker)
        except MercadoError:
            sin_cobertura.append(ticker)

    return {"precios": resultados, "sin_cobertura": sin_cobertura}
