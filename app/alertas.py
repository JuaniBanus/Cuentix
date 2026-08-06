"""Alertas de precio: evaluar umbrales y avisar por Telegram.

Lo corre un cron, no una persona. Eso cambia dos cosas respecto del resto del
bot:

- No hay nadie esperando en pantalla, así que puede tardar. A cambio, tiene que
  ser prolijo con la cuota del proveedor de precios: se consulta UN precio por
  ticker distinto, no uno por alerta. Diez alertas sobre AAPL son una consulta.

- Un fallo no se le puede mostrar a nadie en el momento, así que nada de lo que
  pase acá puede cortar la corrida entera: si una alerta falla, se registra y se
  sigue con las demás.

Cuando una alerta se cumple se APAGA. Un papel que quedó debajo del umbral
seguiría cumpliendo la condición en cada corrida, y mandaría un mensaje por hora
hasta que alguien lo note.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from app.db import DBError, alertas_activas, apagar_alerta
from app.mercado import MercadoError, precio as precio_de_mercado
from app.telegram import TelegramError, enviar_mensaje

logger = logging.getLogger(__name__)

FLECHA = {"baja": "🔻", "sube": "🔺", "debajo": "🔻", "encima": "🔺"}


def _decimal(valor) -> Decimal | None:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _se_cumple(alerta: dict, precio: Decimal) -> tuple[bool, Decimal | None]:
    """¿Se cruzó el umbral? Devuelve (sí/no, variación porcentual si aplica).

    Para baja/sube hace falta la referencia —el precio de cuando se creó—. Sin
    ella no se puede medir un porcentaje contra nada, y se prefiere no disparar
    antes que inventar una base.
    """
    tipo = alerta.get("tipo")
    umbral = _decimal(alerta.get("umbral"))
    if umbral is None:
        return False, None

    if tipo in ("debajo", "encima"):
        return (precio <= umbral if tipo == "debajo" else precio >= umbral), None

    referencia = _decimal(alerta.get("referencia"))
    if not referencia:
        return False, None

    variacion = (precio - referencia) / referencia * 100
    if tipo == "baja":
        return variacion <= -umbral, variacion
    return variacion >= umbral, variacion


def _plata(valor: Decimal, moneda: str | None) -> str:
    """1234.5 -> 'US$1.234,50'. Formato argentino: punto de miles, coma decimal."""
    simbolo = {"ARS": "$", "USD": "US$", "EUR": "€"}.get(moneda or "", "")
    # f-string da "1,234.50" (formato inglés); se dan vuelta los separadores en
    # un solo paso, con un marcador intermedio para no pisarlos entre sí.
    entero = f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{simbolo}{entero}"


def _mensaje(alerta: dict, precio: Decimal, variacion: Decimal | None) -> str:
    ticker = alerta.get("ticker", "?")
    moneda = alerta.get("moneda")
    flecha = FLECHA.get(alerta.get("tipo"), "🔔")

    lineas = [f"{flecha} {ticker} — {_plata(precio, moneda)}"]

    if variacion is not None:
        referencia = _decimal(alerta.get("referencia"))
        signo = "+" if variacion > 0 else ""
        # Coma decimal, como el resto de los números que manda el bot.
        detalle = f"{signo}{variacion:.1f}".replace(".", ",") + "% desde que pusiste la alerta"
        if referencia:
            detalle += f" ({_plata(referencia, moneda)})"
        lineas.append(detalle)
    else:
        umbral = _decimal(alerta.get("umbral"))
        direccion = "por debajo de" if alerta.get("tipo") == "debajo" else "por encima de"
        lineas.append(f"Cruzó {direccion} {_plata(umbral, moneda)}")

    lineas.append("")
    lineas.append("La alerta se apagó para no repetirse. Si querés otra, pedímela.")
    return "\n".join(lineas)


async def revisar() -> dict:
    """Revisa todas las alertas activas y avisa las que se cumplieron.

    Devuelve un resumen para que el cron pueda loguearlo y para poder mirarlo
    desde afuera sin entrar al servidor.
    """
    try:
        alertas = alertas_activas()
    except DBError as exc:
        logger.error("No pude leer las alertas: %s", exc)
        return {"error": str(exc), "revisadas": 0, "disparadas": 0}

    if not alertas:
        return {"revisadas": 0, "disparadas": 0, "sin_precio": 0}

    # Un precio por (ticker, mercado), no uno por alerta: varias alertas sobre
    # el mismo papel comparten la consulta y la cuota.
    precios: dict[tuple[str, str], Decimal] = {}
    sin_precio: set[tuple[str, str]] = set()

    disparadas = 0
    fallos = []

    for alerta in alertas:
        clave = (str(alerta.get("ticker", "")).upper(), alerta.get("mercado") or "us")
        if clave in sin_precio:
            continue

        if clave not in precios:
            try:
                datos = await precio_de_mercado(clave[0], clave[1])
                valor = _decimal(datos.get("precio"))
                if valor is None:
                    sin_precio.add(clave)
                    continue
                precios[clave] = valor
            except MercadoError as exc:
                logger.warning("Sin precio para %s (%s): %s", clave[0], clave[1], exc)
                sin_precio.add(clave)
                continue

        precio = precios[clave]

        try:
            cumple, variacion = _se_cumple(alerta, precio)
            if not cumple:
                continue

            await enviar_mensaje(int(alerta["chat_id"]), _mensaje(alerta, precio, variacion))
            # Se apaga DESPUÉS de avisar: si el envío falla, la alerta queda
            # activa y se reintenta en la próxima corrida. Al revés se perdería
            # el aviso en silencio.
            apagar_alerta(alerta["id"], precio=precio)
            disparadas += 1
        except (TelegramError, DBError, KeyError, ValueError) as exc:
            # Una alerta rota no puede tumbar la corrida de las demás.
            logger.exception("Falló la alerta %s", alerta.get("id"))
            fallos.append({"id": alerta.get("id"), "error": str(exc)})

    resumen = {
        "revisadas": len(alertas),
        "disparadas": disparadas,
        "sin_precio": len(sin_precio),
    }
    if fallos:
        resumen["fallos"] = fallos
    logger.info("Alertas: %s", resumen)
    return resumen
