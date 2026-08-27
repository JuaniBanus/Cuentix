"""Rendimiento REALIZADO de la cartera, para usarlo como costo de oportunidad."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.db import obtener_inversiones
from app.mercado import MercadoError, precio as precio_de_mercado
from app.models import Moneda

logger = logging.getLogger(__name__)

DIAS_MINIMOS = 45

URL_COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
TIEMPO_LIMITE = 8.0

IDS_COINGECKO = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "USDC": "usd-coin",
    "DAI": "dai", "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
    "MATIC": "matic-network", "LINK": "chainlink", "LTC": "litecoin",
    "TRX": "tron", "UNI": "uniswap", "ATOM": "cosmos", "NEAR": "near",
}

_DE_MERCADO = {"accion", "etf", "cedear", "bono"}


class Rendimiento:
    """Lo que rindió la cartera en una moneda."""

    __slots__ = ("tem", "posiciones", "cotizadas", "meses_promedio", "moneda")

    def __init__(
        self, tem: Decimal, posiciones: int, cotizadas: int,
        meses_promedio: Decimal, moneda: Moneda,
    ) -> None:
        self.tem = tem
        self.posiciones = posiciones
        self.cotizadas = cotizadas
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


async def rendimiento(
    moneda: Moneda, hoy: date | None = None, *, user_id: str
) -> Rendimiento | None:
    """La tasa mensual realizada de la cartera en esa moneda, o None."""
    hoy = hoy or date.today()

    todas = obtener_inversiones(user_id=user_id, limite=200)
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
            continue

        ticker = str(inversion.get("ticker") or "").upper()
        if inversion.get("tipo") == "cripto":
            actual = precios_cripto.get(ticker)
        else:
            actual = await _precio_de(inversion, moneda)
        if actual is None or actual <= 0:
            continue

        valor = cantidad * actual
        meses = Decimal(dias) / Decimal("30.44")

        try:
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
