"""Rendimientos de billeteras virtuales: de dónde salen las tasas."""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

URL_FONDOS = "https://api.argentinadatos.com/v1/finanzas/fci/fondos"
URL_ENTIDADES = "https://api.argentinadatos.com/v1/finanzas/rendimientos"

TIEMPO_LIMITE = 90.0

TNA_MAXIMA = Decimal("300")
UN_MES_MAXIMO = Decimal("50")

CATALOGO_FCI: tuple[tuple[str, str, Decimal | None], ...] = (
    ("Mercado Pago", "Mercado Fondo - Clase A", None),
    ("Mercado Pago (Bonos y plazos fijos)", "MP Ahorro - Clase A", None),
    ("Ualá", "Ualintec Ahorro Pesos - Clase A", None),
    ("Ualá (Pesos Plus)", "Ualintec Pesos Plus - Clase A", None),
    ("Personal Pay", "Delta Pesos - Clase X", None),
    ("Fiwind", "Delta Pesos - Clase A", None),
    ("Lemon", "Vinci Compass Liquidez - Clase F", None),
    ("Prex", "Allaria Ahorro - Clase E", None),
    ("Claro Pay", "SBS Ahorro Pesos - Clase A", None),
    ("CencoPay", "SBS Ahorro Pesos - Clase A", None),
    ("Cocos Ahorro", "Cocos Ahorro - Clase A", None),
    ("Cocos Pesos Plus", "Cocos Pesos Plus - Clase A", None),
    ("Cocos Rendimiento", "Cocos Rendimiento - Clase A", None),
    ("Astropay", "ST Zero - Clase D", None),
    ("LB Finanzas", "ST Zero - Clase D", None),
    ("Balanz", "Balanz Capital Money Market - Clase A", None),
    ("IOL", "IOL Cash Management - Clase A", None),
    ("IEB+", "Ciclo Nova Ahorro - Clase A", None),
    ("Adcap", "Adcap Ahorro Pesos Fondo de Dinero - Clase A", None),
    ("Toronto Ahorro", "Toronto Trust Ahorro - Clase A", None),
    ("Banco Galicia", "Fima Premium - Clase A", None),
    ("Banco Santander", "Super Ahorro $ - Clase A", None),
    ("YPF App", "Super Ahorro $ - Clase A", None),
    ("Banco Macro", "Pionero Pesos - Clase A", None),
    ("Banco Supervielle", "Premier Renta CP en Pesos - Clase A", None),
    ("ICBC", "Alpha Pesos - Clase A", None),
)

NOMBRES_ENTIDADES: dict[str, str] = {
    "fiwind": "Fiwind (cuenta remunerada)",
    "letsbit": "Let'sBit",
    "lemoncash": "Lemon (cuenta remunerada)",
    "belo": "Belo",
    "ripio": "Ripio",
    "satoshitango": "SatoshiTango",
    "prex": "Prex (cuenta remunerada)",
}


class RendimientosError(RuntimeError):
    """No se pudo traer una de las fuentes. Se maneja adentro del módulo."""


def _decimal(valor: object) -> Decimal | None:
    """A Decimal, o None si no es un número usable. Nunca levanta."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return numero if numero.is_finite() else None


def _fecha(valor: object) -> date | None:
    """'2026-08-14' -> date. None si no se puede leer."""
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _leer_fondos(nombres: set[str]) -> dict[str, dict]:
    """Los fondos pedidos, leyendo la respuesta DE A UN OBJETO POR VEZ."""
    decodificador = json.JSONDecoder()
    encontrados: dict[str, dict] = {}
    buffer = ""
    arrancado = False

    with httpx.stream("GET", URL_FONDOS, timeout=TIEMPO_LIMITE) as respuesta:
        respuesta.raise_for_status()

        for pedazo in respuesta.iter_text(65536):
            buffer += pedazo

            if not arrancado:
                inicio = buffer.find('"fondos"')
                if inicio == -1:
                    continue
                corchete = buffer.find("[", inicio)
                if corchete == -1:
                    continue
                buffer = buffer[corchete + 1:]
                arrancado = True

            while True:
                resto = buffer.lstrip()
                if resto[:1] == ",":
                    buffer = resto[1:]
                    continue
                if not resto or resto[0] == "]":
                    buffer = resto
                    break
                try:
                    objeto, fin = decodificador.raw_decode(resto)
                except json.JSONDecodeError:
                    buffer = resto
                    break

                buffer = resto[fin:]
                nombre = objeto.get("nombre")
                if nombre in nombres:
                    encontrados[nombre] = objeto


    if not arrancado:
        raise RendimientosError(
            "la respuesta no tiene el array 'fondos' (¿cambió el formato de la API?)"
        )

    return encontrados


def _filas_de_fondos() -> list[dict]:
    """Una fila por billetera del catálogo cuyo fondo se pudo leer."""
    nombres = {fondo for _, fondo, _ in CATALOGO_FCI}

    try:
        fondos = _leer_fondos(nombres)
    except (httpx.HTTPError, ValueError) as exc:
        raise RendimientosError(f"No pude leer los fondos: {exc}") from exc

    filas: list[dict] = []
    sin_datos: list[str] = []

    for billetera, fondo, tope in CATALOGO_FCI:
        datos = fondos.get(fondo)
        if datos is None:
            sin_datos.append(billetera)
            continue

        un_mes = _decimal((datos.get("rendimientos") or {}).get("unMes"))
        cuando = _fecha(datos.get("fecha"))

        if un_mes is None or cuando is None:
            sin_datos.append(billetera)
            continue
        if not (0 <= un_mes <= UN_MES_MAXIMO):
            logger.warning("Rendimiento mensual fuera de rango en %s: %s", fondo, un_mes)
            sin_datos.append(billetera)
            continue

        tna = un_mes * 12
        if not (0 <= tna < TNA_MAXIMA):
            sin_datos.append(billetera)
            continue

        filas.append({
            "nombre": billetera,
            "tipo": "fci",
            "tna": str(tna.quantize(Decimal("0.0001"))),
            "tope_monto": str(tope) if tope is not None else None,
            "fecha_actualizacion": cuando.isoformat(),
            "fondo": fondo,
            "fuente": "argentinadatos/fci",
        })

    if not filas:
        raise RendimientosError(
            "ningún fondo del catálogo apareció en la respuesta "
            "(¿cambiaron los nombres en la CAFCI?)"
        )

    if sin_datos:
        logger.warning("Sin datos de fondo para: %s", ", ".join(sin_datos))

    return filas


def _filas_de_entidades() -> list[dict]:
    """Las entidades que declaran una tasa en PESOS."""
    try:
        with httpx.Client(timeout=TIEMPO_LIMITE, follow_redirects=True) as cliente:
            respuesta = cliente.get(URL_ENTIDADES)
            respuesta.raise_for_status()
            datos = respuesta.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RendimientosError(f"No pude leer las entidades: {exc}") from exc

    filas: list[dict] = []

    for entidad in datos if isinstance(datos, list) else []:
        if not isinstance(entidad, dict):
            continue
        clave = str(entidad.get("entidad") or "").strip().lower()
        if not clave:
            continue

        for rendimiento in entidad.get("rendimientos") or []:
            if not isinstance(rendimiento, dict):
                continue
            if str(rendimiento.get("moneda") or "").upper() != "ARS":
                continue

            tna = _decimal(rendimiento.get("apy"))
            cuando = _fecha(rendimiento.get("fecha"))
            if tna is None or cuando is None or not (0 <= tna < TNA_MAXIMA):
                continue

            tope = _decimal(rendimiento.get("bonusThreshold"))

            filas.append({
                "nombre": NOMBRES_ENTIDADES.get(clave, clave.title()),
                "tipo": "cuenta_remunerada",
                "tna": str(tna.quantize(Decimal("0.0001"))),
                "tope_monto": str(tope) if tope is not None and tope > 0 else None,
                "fecha_actualizacion": cuando.isoformat(),
                "fondo": None,
                "fuente": "argentinadatos/entidades",
            })
            break

    if not filas:
        logger.info("Ninguna entidad declara rendimiento en pesos")

    return filas


def actualizar() -> dict:
    """Trae las tasas de las dos fuentes y las guarda. NUNCA levanta."""
    from app.db import DBError, guardar_rendimientos

    filas: list[dict] = []
    problemas: list[str] = []

    for nombre_fuente, traer in (("fondos", _filas_de_fondos), ("entidades", _filas_de_entidades)):
        try:
            filas.extend(traer())
        except RendimientosError as exc:
            logger.warning("Falló la fuente de %s: %s", nombre_fuente, exc)
            problemas.append(f"{nombre_fuente}: {exc}")
        except Exception as exc:  # noqa: BLE001 - el cron no puede caerse por esto
            logger.exception("Error inesperado en la fuente de %s", nombre_fuente)
            problemas.append(f"{nombre_fuente}: error inesperado ({exc})")

    if not filas:
        logger.error("Ninguna fuente respondió; se conservan las tasas anteriores")
        return {"ok": False, "guardadas": 0, "problemas": problemas or ["sin datos"]}

    unicas: dict[str, dict] = {}
    for fila in filas:
        unicas[fila["nombre"]] = fila

    try:
        guardadas = guardar_rendimientos(list(unicas.values()))
    except DBError as exc:
        logger.error("No pude guardar los rendimientos: %s", exc)
        return {"ok": False, "guardadas": 0, "problemas": problemas + [str(exc)]}

    resumen = {
        "ok": not problemas,
        "guardadas": guardadas,
        "fci": sum(1 for f in unicas.values() if f["tipo"] == "fci"),
        "cuentas_remuneradas": sum(
            1 for f in unicas.values() if f["tipo"] == "cuenta_remunerada"
        ),
    }
    if problemas:
        resumen["problemas"] = problemas

    logger.info("Rendimientos actualizados: %s", resumen)
    return resumen
