"""Proxy de precios de mercado: acciones, CEDEARs e índices.

============================ POR QUÉ UN PROXY ============================

Por dos motivos distintos, y conviene no confundirlos porque aplican a
proveedores distintos:

1. LA CLAVE. Twelve Data pide una API key. Si la web llamara directo, la clave
   viajaría en el JavaScript y cualquiera la leería con Ctrl+U, igual que
   pasaría con la service_role de Supabase. (Curiosidad verificada: Twelve Data
   y Finnhub SÍ mandan Access-Control-Allow-Origin: *, así que desde el
   navegador funcionarían. El problema no es CORS ahí, es la clave.)

2. CORS. Data912, que es de donde salen los papeles argentinos, NO manda
   ningún header de CORS. Verificado con curl: el navegador bloquea la llamada
   antes de que salga. Ahí el proxy es la única salida, aunque no haya clave.

============================ EL PRESUPUESTO ============================

El plan gratuito de Twelve Data da 800 llamadas por día y 8 por minuto, y el
contador diario se reinicia a medianoche UTC. Con eso, cachear no es una
optimización: sin caché, una sola pantalla abierta un rato agota la cuota.

El caché es un diccionario en memoria, y eso condiciona dónde puede vivir esto
—ver la nota de arriba de todo en el endpoint—: el proceso tiene que sobrevivir
entre pedidos para que el caché sirva de algo.

Cuando el presupuesto se agota, NO se devuelve un error: se sirve lo último que
haya, marcado como vencido. Un precio de hace una hora dice bastante más que
una pantalla en blanco, siempre que la respuesta admita que es viejo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import TWELVE_DATA_API_KEY

logger = logging.getLogger(__name__)

URL_TWELVE = "https://api.twelvedata.com"
URL_DATA912 = "https://data912.com"

# Cuánto vale un dato antes de volver a pedirlo. Media hora es el punto donde
# el presupuesto alcanza cómodo: con 30 minutos, seguir diez símbolos toda la
# rueda son ~320 llamadas de las 800 del día.
TTL_SEGUNDOS = 30 * 60

# Freno propio, más bajo que el del proveedor, para no llegar nunca al 429:
# el límite real es 800/día y 8/minuto.
TOPE_DIARIO = 700
TOPE_POR_MINUTO = 6

TIEMPO_LIMITE = 10.0

# Los papeles argentinos no están en Twelve Data; salen de Data912, que además
# devuelve la rueda entera en un solo pedido y por eso se cachea como un bloque.
LISTAS_ARG = ("arg_stocks", "arg_cedears", "arg_bonds")


class MercadoError(RuntimeError):
    """No se pudo obtener el precio."""


class SinClave(MercadoError):
    """Falta configurar TWELVE_DATA_API_KEY."""


class ValorInvalido(MercadoError):
    """El pedido está mal armado. Es culpa de quien llama, no del proveedor."""


# --------------------------------------------------------------------------
# Caché y presupuesto
# --------------------------------------------------------------------------

_cache: dict[str, tuple[Any, float]] = {}
_cliente: httpx.AsyncClient | None = None

# Llamadas gastadas hoy, con el día al que corresponden para poder reiniciar.
_gastadas = 0
_dia_utc = ""
# Marcas de tiempo de las últimas llamadas, para el freno por minuto.
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
    if _dia_utc != _hoy_utc():  # cambió el día: el proveedor reinicia a las 00 UTC
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
    presupuesto()  # reinicia el contador si cambió el día
    _gastadas += 1
    _recientes.append(time.monotonic())


def _guardado(clave: str) -> tuple[Any, bool] | None:
    """(dato, vencido) o None si nunca se pidió."""
    if clave not in _cache:
        return None
    dato, momento = _cache[clave]
    return dato, (time.monotonic() - momento) > TTL_SEGUNDOS


def _guardar(clave: str, dato: Any) -> None:
    _cache[clave] = (dato, time.monotonic())


# --------------------------------------------------------------------------
# Twelve Data
# --------------------------------------------------------------------------


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
    # Twelve Data contesta 200 con {"code": 4xx, "message": ...} en vez de un
    # status HTTP de error, así que mirar respuesta.status_code no alcanza.
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
    return n if n == n else None  # descarta NaN


def _redondear(valor: float | None) -> float | None:
    """Dos decimales. El proveedor manda cosas como 0.3778135, y siete
    decimales en un porcentaje sugieren una precisión que el dato no tiene."""
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
    """El cierre de hace N ruedas. Cuenta ruedas y no días de calendario: una
    semana de mercado son 5, no 7, y un feriado no debe correr la referencia."""
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
            # La diaria la da el propio proveedor: es contra el cierre anterior
            # y no contra la apertura, que es lo que se entiende por "hoy".
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
        "fuente": "twelvedata",
    }


# --------------------------------------------------------------------------
# Data912 (papeles argentinos, sin clave)
# --------------------------------------------------------------------------


async def _rueda_argentina(lista: str) -> list[dict]:
    """Una lista entera de Data912, cacheada como bloque.

    Devuelve la rueda completa en un solo pedido, así que traer diez papeles
    cuesta lo mismo que traer uno. No consume presupuesto: no tiene clave ni
    límite publicado.
    """
    clave = f"arg:{lista}"
    if (previo := _guardado(clave)) and not previo[1]:
        return previo[0]

    try:
        respuesta = await _obtener_cliente().get(f"{URL_DATA912}/live/{lista}")
        respuesta.raise_for_status()
        filas = respuesta.json()
    except (httpx.HTTPError, ValueError) as exc:
        if previo:
            return previo[0]  # vencido, pero es lo que hay
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
                    # Data912 solo da la variación del día. Semana y mes
                    # quedan en null: es un dato que no tenemos, y rellenarlo
                    # con cero diría "no se movió", que es distinto.
                    "variacion": {"dia": _numero(fila.get("pct_change")), "semana": None, "mes": None},
                    "rango_dia": {"min": None, "max": None},
                    "rango_52_semanas": {"min": None, "max": None},
                    "actualizado": None,
                    "fuente": f"data912:{lista}",
                }
    return None


# --------------------------------------------------------------------------
# Lo que usan los endpoints
# --------------------------------------------------------------------------


async def precio(ticker: str, mercado: str = "us") -> dict:
    """Precio y variaciones de una acción o CEDEAR.

    `mercado` es OBLIGATORIO en la práctica aunque tenga default, porque el
    mismo ticker puede ser dos activos distintos: AAPL es la acción de Apple en
    NASDAQ a US$311 y también el CEDEAR de Apple en BYMA a $24.630. Elegir por
    nuestra cuenta y no decirlo devolvería un número plausible y equivocado,
    que es la peor clase de error para un precio.

    - "us": Twelve Data. Gasta cuota.
    - "ar": Data912, mercado argentino. No gasta cuota ni pide clave.
    """
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 20:
        raise ValorInvalido("Ticker inválido.")

    mercado = (mercado or "us").strip().lower()
    if mercado not in ("us", "ar"):
        raise ValorInvalido("El mercado tiene que ser «us» o «ar».")

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
    """Serie de cierres diarios, del más viejo al más nuevo, para graficar.

    Va en su propio endpoint y no dentro de /api/precio porque son ~90 puntos
    por activo: pegarlos a cada consulta de precio engordaría la respuesta que
    más se pide para servir a la pantalla que menos se abre.
    """
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 20:
        raise ValorInvalido("Ticker inválido.")

    mercado = (mercado or "us").strip().lower()
    if mercado not in ("us", "ar"):
        raise ValorInvalido("El mercado tiene que ser «us» o «ar».")

    dias = max(7, min(int(dias or 90), 365))

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
                # El proveedor los manda del más nuevo al más viejo; un gráfico
                # se lee al revés, así que se invierten una sola vez acá.
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


# Los índices se piden con el símbolo que usa cada proveedor. El "^" es la
# convención de Yahoo y Twelve Data no lo quiere, así que se traduce acá en vez
# de obligar a la web a saber de estas diferencias.
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
