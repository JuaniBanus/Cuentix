"""Cupo diario de consumo de APIs externas, persistido en Supabase."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from postgrest import APIError

from app.db import _obtener_cliente

logger = logging.getLogger(__name__)

SERVICIO_MERCADO = "mercado"

TOPE_REFRESCOS_DIA = 5
TOPE_UNIDADES_DIA = 100
TOPE_GLOBAL_DIA = 700
TOPE_TICKERS_DIA = 40

MOTIVOS = {
    "refrescos": (
        f"Llegaste a las {TOPE_REFRESCOS_DIA} actualizaciones de precios de hoy. "
        "Te muestro los últimos valores que tengo guardados."
    ),
    "unidades": (
        "Alcanzaste el consumo diario de datos de mercado. "
        "Te muestro los últimos valores que tengo guardados."
    ),
    "global": (
        "Se agotó la cuota de precios del día para todo Cuentix. "
        "Te muestro los últimos valores que tengo guardados."
    ),
}


class CupoAgotado(RuntimeError):
    """El usuario o el sistema se quedaron sin cupo. Trae el motivo y el estado."""

    def __init__(self, motivo: str, estado: dict[str, Any]) -> None:
        super().__init__(MOTIVOS.get(motivo, "Sin cupo por hoy."))
        self.motivo = motivo
        self.estado = estado


def consumir(
    user_id: str,
    unidades: int,
    refrescos: int = 0,
    tickers: list[str] | None = None,
    servicio: str = SERVICIO_MERCADO,
) -> dict[str, Any]:
    """Cobra `unidades` del cupo del usuario, o levanta CupoAgotado sin cobrar."""
    try:
        respuesta = _obtener_cliente().rpc(
            "consumir_cupo",
            {
                "p_user_id": user_id,
                "p_servicio": servicio,
                "p_unidades": unidades,
                "p_refrescos": refrescos,
                "p_tickers": tickers or [],
                "p_tope_refrescos": TOPE_REFRESCOS_DIA,
                "p_tope_unidades": TOPE_UNIDADES_DIA,
                "p_tope_global": TOPE_GLOBAL_DIA,
            },
        ).execute()
    except APIError as exc:
        # Que falle la contabilidad no puede dejar sin precios a un usuario
        # legítimo: se registra y se sigue. El tope global del proveedor, que es
        # el que protege la cuota de verdad, se aplica igual en mercado.py.
        logger.warning("No se pudo registrar el consumo de %s: %s", user_id, exc)
        return {"permitido": True, "motivo": None, "sin_registro": True}

    estado = respuesta.data or {}
    if not estado.get("permitido"):
        raise CupoAgotado(str(estado.get("motivo") or ""), estado)
    return estado


def restante(user_id: str, servicio: str = SERVICIO_MERCADO) -> dict[str, Any]:
    """Lo gastado hoy por el usuario, para mostrarlo en pantalla."""
    try:
        respuesta = _obtener_cliente().rpc(
            "cupo_restante", {"p_user_id": user_id, "p_servicio": servicio}
        ).execute()
    except APIError as exc:
        logger.warning("No se pudo leer el cupo de %s: %s", user_id, exc)
        return {}

    gastado = respuesta.data or {}
    return {
        "refrescos_usados": gastado.get("refrescos", 0),
        "refrescos_tope": TOPE_REFRESCOS_DIA,
        "unidades_usadas": gastado.get("unidades", 0),
        "unidades_tope": TOPE_UNIDADES_DIA,
    }


def barriendo(estado: dict[str, Any]) -> bool:
    """Si el patrón de tickers del día parece un barrido y no un portafolio."""
    return int(estado.get("tickers") or 0) > TOPE_TICKERS_DIA


def global_hoy(servicio: str = SERVICIO_MERCADO) -> dict[str, Any]:
    """Lo gastado hoy contra el proveedor, según la base y no según el proceso."""
    hoy = datetime.now(timezone.utc).date().isoformat()
    try:
        filas = (
            _obtener_cliente()
            .table("consumo_global")
            .select("unidades")
            .eq("dia", hoy)
            .eq("servicio", servicio)
            .limit(1)
            .execute()
        ).data or []
    except APIError as exc:
        logger.warning("No se pudo leer el consumo global: %s", exc)
        return {}

    gastadas = int(filas[0]["unidades"]) if filas else 0
    return {
        "dia": hoy,
        "gastadas": gastadas,
        "tope": TOPE_GLOBAL_DIA,
        "restantes": max(0, TOPE_GLOBAL_DIA - gastadas),
    }
