"""Rendimiento REALIZADO de la cartera, para usarlo como costo de oportunidad.

Contesta una pregunta concreta: la plata que el usuario ya tiene invertida,
¿a qué ritmo mensual vino rindiendo? Ese número sirve como tasa alternativa al
plazo fijo cuando se compara cuotas contra contado.

CÓMO SE CALCULA
Por posición: rendimiento total = valor_actual / costo, y de ahí la tasa
mensual equivalente con (valor/costo)^(1/meses) - 1. La tasa de la cartera es
el promedio de esas, PONDERADO POR COSTO: una posición de $10.000 no puede
pesar lo mismo que una de $1.000.000.

Se anualiza geométricamente y no dividiendo: un 20% en dos meses no es 10%
por mes, es 9,54%. La diferencia se agranda con los plazos largos.

LO QUE ESTE NÚMERO NO ES
Es rendimiento PASADO. No predice nada, y en una cartera chica o nueva puede
ser cualquier cosa: una cripto que subió 40% en seis semanas da una tasa
mensual altísima que no se va a repetir. Por eso:

- Se exige un mínimo de historia por posición (`DIAS_MINIMOS`). Anualizar diez
  días da números absurdos.
- Se calcula POR MONEDA. El rendimiento nominal en pesos y en dólares no son
  comparables: el primero incluye la inflación y el segundo no. Para descontar
  cuotas en pesos hace falta la tasa en pesos.
- Quien lo usa muestra TAMBIÉN el resultado con la tasa del plazo fijo, para
  que se vea de dónde sale la conclusión en vez de esconderlo en un promedio.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.db import obtener_inversiones
from app.mercado import MercadoError, precio as precio_de_mercado
from app.models import Moneda

logger = logging.getLogger(__name__)

# Menos que esto y la tasa mensual equivalente es ruido amplificado.
DIAS_MINIMOS = 45

URL_COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
TIEMPO_LIMITE = 8.0

# Los mismos ids que usa la web. Lo que no esté acá queda sin cotizar y se dice.
IDS_COINGECKO = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "USDC": "usd-coin",
    "DAI": "dai", "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
    "MATIC": "matic-network", "LINK": "chainlink", "LTC": "litecoin",
    "TRX": "tron", "UNI": "uniswap", "ATOM": "cosmos", "NEAR": "near",
}

# Tipos que el proxy de mercado puede cotizar.
_DE_MERCADO = {"accion", "etf", "cedear", "bono"}


class Rendimiento:
    """Lo que rindió la cartera en una moneda."""

    __slots__ = ("tem", "posiciones", "cotizadas", "meses_promedio", "moneda")

    def __init__(
        self, tem: Decimal, posiciones: int, cotizadas: int,
        meses_promedio: Decimal, moneda: Moneda,
    ) -> None:
        self.tem = tem                    # tasa efectiva mensual realizada
        self.posiciones = posiciones      # cuántas hay en esa moneda
        self.cotizadas = cotizadas        # de cuántas se pudo obtener precio
        self.meses_promedio = meses_promedio
        self.moneda = moneda


async def _precios_cripto(tickers: list[str]) -> dict[str, Decimal]:
    """Precios en USD de CoinGecko. Devuelve {} ante cualquier problema."""
    ids = {t: IDS_COINGECKO[t] for t in tickers if t in IDS_COINGECKO}
    if not ids:
        return {}

    try:
        async with httpx.AsyncClient(timeout=TIEMPO_LIMITE) as cliente:
            respuesta = await cliente.get(
                URL_COINGECKO,
                params={"ids": ",".join(sorted(set(ids.values()))), "vs_currencies": "usd"},
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
    except Exception:
        logger.warning("No pude traer precios de CoinGecko", exc_info=True)
        return {}

    precios = {}
    for ticker, gecko_id in ids.items():
        valor = (datos.get(gecko_id) or {}).get("usd")
        try:
            if valor is not None:
                precios[ticker] = Decimal(str(valor))
        except (InvalidOperation, ValueError):
            continue
    return precios


async def _precio_de(inversion: dict, moneda: Moneda) -> Decimal | None:
    """Precio actual de una tenencia que no es cripto, vía el proxy."""
    ticker = str(inversion.get("ticker") or "").strip().upper()
    if not ticker or inversion.get("tipo") not in _DE_MERCADO:
        return None

    # Una tenencia en pesos cotiza en BYMA y una en dólares en el mercado
    # estadounidense: AAPL existe en los dos y son activos distintos.
    plaza = "ar" if moneda is Moneda.ARS else "us"
    try:
        datos = await precio_de_mercado(ticker, plaza)
    except MercadoError:
        return None
    except Exception:
        logger.warning("Error inesperado cotizando %s", ticker, exc_info=True)
        return None

    try:
        crudo = datos.get("precio")
        return Decimal(str(crudo)) if crudo is not None else None
    except (InvalidOperation, ValueError):
        return None


async def rendimiento(moneda: Moneda, hoy: date | None = None) -> Rendimiento | None:
    """La tasa mensual realizada de la cartera en esa moneda, o None.

    None significa "no se pudo calcular", que puede ser porque no hay
    tenencias en esa moneda, porque son muy nuevas o porque ningún proveedor
    las cotiza. Quien llama tiene que poder distinguir eso de un 0%.
    """
    hoy = hoy or date.today()

    todas = obtener_inversiones(limite=200)
    de_la_moneda = [i for i in todas if i.get("moneda") == moneda.value]
    if not de_la_moneda:
        return None

    cripto = [
        str(i.get("ticker") or "").upper()
        for i in de_la_moneda
        if i.get("tipo") == "cripto"
    ]
    precios_cripto = await _precios_cripto([t for t in cripto if t])

    peso_total = Decimal("0")
    suma_ponderada = Decimal("0")
    meses_ponderados = Decimal("0")
    cotizadas = 0

    for inversion in de_la_moneda:
        try:
            cantidad = Decimal(str(inversion["cantidad"]))
            costo_unitario = Decimal(str(inversion["precio_compra"]))
            comprada = date.fromisoformat(inversion["fecha_compra"])
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue

        costo = cantidad * costo_unitario
        if costo <= 0:
            continue

        dias = (hoy - comprada).days
        if dias < DIAS_MINIMOS:
            continue  # muy nueva: anualizarla seria inventar

        ticker = str(inversion.get("ticker") or "").upper()
        if inversion.get("tipo") == "cripto":
            actual = precios_cripto.get(ticker)
        else:
            actual = await _precio_de(inversion, moneda)
        if actual is None or actual <= 0:
            continue

        valor = cantidad * actual
        meses = Decimal(dias) / Decimal("30.44")  # promedio de días por mes

        try:
            # (valor/costo)^(1/meses) - 1, con floats porque Decimal no hace
            # potencias fraccionarias. La precisión de float sobra para una tasa.
            factor = float(valor / costo)
            if factor <= 0:
                continue
            tem_posicion = Decimal(str(factor ** (1 / float(meses)) - 1))
        except (OverflowError, ValueError, ZeroDivisionError):
            continue

        suma_ponderada += tem_posicion * costo
        meses_ponderados += meses * costo
        peso_total += costo
        cotizadas += 1

    if not cotizadas or peso_total <= 0:
        return None

    return Rendimiento(
        tem=(suma_ponderada / peso_total).quantize(Decimal("0.00001")),
        posiciones=len(de_la_moneda),
        cotizadas=cotizadas,
        meses_promedio=(meses_ponderados / peso_total).quantize(Decimal("0.1")),
        moneda=moneda,
    )
