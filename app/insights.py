"""Recomendaciones sobre los gastos, a partir de agregados y no de movimientos.

Lo que entra acá ya viene sumado y contado por la web: totales por categoría,
variaciones contra el período anterior, promedios y candidatos a cargo
recurrente. Nunca entra el texto de los mensajes de Telegram ni la lista de
movimientos uno por uno.

Eso no es una formalidad: reduce lo que sale del navegador a unas decenas de
números, hace la llamada barata y acotada, y deja el análisis sin material con
el que reconstruir la vida de nadie. Gemini recibe "supermercado: 320.000,
+18% contra el mes pasado", no "compré pañales el martes".

La otra mitad del diseño está en la web (web/js/insights.js), que es la que
calcula los agregados: acá solo se los interpreta.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

MODELO = "gemini-3.5-flash-lite"

# Cliente propio y no el de parser.py: son dos usos distintos del mismo
# proveedor y no conviene que un cambio de configuración en uno toque al otro.
_cliente = genai.Client(api_key=GEMINI_API_KEY)

# Tope de insights. Más que esto no es un panel, es un informe que nadie lee.
MAX_INSIGHTS = 5


class InsightsError(RuntimeError):
    """No se pudieron generar los insights."""


# --------------------------------------------------------------------------
# Lo que manda la web
# --------------------------------------------------------------------------


class CategoriaAgregada(BaseModel):
    """Una categoría con su total del período y cómo viene contra el anterior."""

    categoria: str = Field(max_length=60)
    total: Decimal
    porcentaje: float = Field(description="Qué parte del gasto del período se lleva")
    # None cuando la categoría no existía antes: no es un crecimiento del
    # infinito por ciento, es una categoría nueva, y se dice distinto.
    variacion_pct: float | None = None
    total_anterior: Decimal | None = None
    promedio_mensual: Decimal | None = None


class CargoRecurrente(BaseModel):
    """Un cargo que se repite mes a mes por un monto parecido.

    Lo detecta la web con una regla explícita (mismo concepto, monto similar,
    varios meses seguidos). Acá llega como candidato, no como certeza: por eso
    los insights hablan de "posible suscripción" y nunca afirman que lo sea.
    """

    concepto: str = Field(max_length=80)
    monto_tipico: Decimal
    veces: int
    meses_seguidos: int
    ultimo_mes: str = Field(max_length=7, description="AAAA-MM")
    # Cuánto varía el importe entre repeticiones. Es lo que distingue un abono
    # —siempre el mismo precio— de un gasto que solo se repite, como la compra
    # semanal. Sin este dato los dos llegan iguales y el análisis los confunde.
    dispersion_pct: float = 0.0
    categoria: str | None = Field(default=None, max_length=60)


class AgregadosGastos(BaseModel):
    """Todo lo que el análisis necesita saber. Nada de esto identifica a nadie."""

    moneda: str = Field(max_length=3)
    periodo: str = Field(max_length=40, description="Cómo llamarlo en el texto")
    meses_analizados: int

    total_periodo: Decimal
    total_anterior: Decimal | None = None
    variacion_total_pct: float | None = None
    promedio_mensual: Decimal | None = None

    ingreso_periodo: Decimal | None = None

    categorias: list[CategoriaAgregada] = Field(default_factory=list, max_length=30)
    recurrentes: list[CargoRecurrente] = Field(default_factory=list, max_length=20)


# --------------------------------------------------------------------------
# Lo que devuelve Gemini
# --------------------------------------------------------------------------


class Insight(BaseModel):
    tipo: str = Field(description="ahorro | crecimiento | suscripcion | consejo")
    titulo: str = Field(max_length=70)
    detalle: str = Field(max_length=320)
    # La categoría o concepto del que habla, para poder resaltarlo en la web.
    referencia: str | None = Field(default=None, max_length=80)


class Insights(BaseModel):
    insights: list[Insight] = Field(default_factory=list, max_length=MAX_INSIGHTS)


_INSTRUCCION = f"""\
Sos un analista de finanzas personales. Te dan NÚMEROS YA CALCULADOS sobre los
gastos de una persona en Argentina y devolvés observaciones útiles, concretas y
breves, en español rioplatense, tuteando (vos).

Devolvés como mucho {MAX_INSIGHTS} insights, ordenados del más útil al menos.
Menos es mejor: si solo hay dos cosas que valen la pena, devolvé dos.

TIPOS
- "ahorro": dónde se puede recortar sin drama, con el monto en juego.
- "crecimiento": una categoría que subió bastante más que el resto.
- "suscripcion": un cargo recurrente que quizá ya no se usa. Vienen en
  "recurrentes" y son CANDIDATOS: hablá de "posible" y sugerí revisarlo.
  Nunca afirmes que la persona no lo usa: no tenés forma de saberlo.
  Mirá la dispersión antes de llamarlo suscripción: un abono cobra casi
  siempre lo mismo (dispersión menor a ~5%). Con dispersión alta es un gasto
  que se repite —la compra del súper, la nafta—, NO un abono; si igual lo
  mencionás, tratalo como gasto habitual y no como algo para dar de baja.
  Si el último mes no es el más reciente del análisis, el cargo dejó de
  aparecer: decilo así ("dejó de figurar desde…"), que es distinto.
- "consejo": una recomendación general que se apoye en estos números.

REGLAS QUE NO SE ROMPEN
1. Usá SOLO los números que te dan. No inventes categorías, montos, fechas ni
   comparaciones con "el promedio argentino" ni con ninguna referencia externa.
2. Cada insight que mencione plata tiene que citar un monto que esté en los
   datos. Si no hay número que lo sostenga, no lo digas.
3. Una categoría sin total_anterior es NUEVA: no calcules un porcentaje de
   crecimiento sobre cero, decí que apareció este período.
4. Si los datos son pocos o poco concluyentes, decilo y devolvé menos insights.
   Es preferible un panel corto y honesto a cinco observaciones inventadas.
5. Nada de moralizar ni de retar. Ni "gastás demasiado en salidas". El tono es
   el de alguien que te muestra un número que no habías visto.
6. No des consejos de inversión ni recomendaciones de productos financieros.

FORMATO
- titulo: una línea corta y concreta. "Delivery subió 40% este mes".
- detalle: dos o tres oraciones como mucho, con el número que lo respalda y,
  si corresponde, qué se podría hacer.
- referencia: la categoría o el concepto del que hablás, tal cual vino.
"""


def _resumen_para_el_modelo(datos: AgregadosGastos) -> str:
    """Arma el texto que ve Gemini. Explícito y sin JSON crudo, que lee peor."""
    partes = [
        f"Moneda: {datos.moneda}",
        f"Período: {datos.periodo} (se analizaron {datos.meses_analizados} meses)",
        f"Gasto del período: {datos.total_periodo}",
    ]
    if datos.total_anterior is not None:
        partes.append(f"Gasto del período anterior: {datos.total_anterior}")
    if datos.variacion_total_pct is not None:
        partes.append(f"Variación del total: {datos.variacion_total_pct:+.1f}%")
    if datos.promedio_mensual is not None:
        partes.append(f"Promedio mensual de gasto: {datos.promedio_mensual}")
    if datos.ingreso_periodo is not None:
        partes.append(f"Ingresos del período: {datos.ingreso_periodo}")

    partes.append("\nGASTO POR CATEGORÍA (de mayor a menor):")
    for c in datos.categorias:
        linea = f"- {c.categoria}: {c.total} ({c.porcentaje:.0f}% del total)"
        if c.total_anterior is None:
            linea += " · no tenía gastos en el período anterior"
        elif c.variacion_pct is not None:
            linea += f" · {c.variacion_pct:+.1f}% contra {c.total_anterior}"
        if c.promedio_mensual is not None:
            linea += f" · promedio mensual {c.promedio_mensual}"
        partes.append(linea)

    if datos.recurrentes:
        partes.append("\nPOSIBLES CARGOS RECURRENTES (candidatos, no confirmados):")
        for r in datos.recurrentes:
            partes.append(
                f"- {r.concepto}: {r.monto_tipico} · apareció {r.veces} veces, "
                f"{r.meses_seguidos} meses seguidos, último {r.ultimo_mes}"
                f" · el importe varía {r.dispersion_pct:.1f}%"
                + (f" · categoría {r.categoria}" if r.categoria else "")
            )
    else:
        partes.append("\nNo se detectaron cargos recurrentes.")

    return "\n".join(partes)


def generar(datos: AgregadosGastos) -> list[Insight]:
    """Le pide a Gemini que interprete los agregados.

    Raises:
        InsightsError: si el modelo no responde o devuelve algo inutilizable.
    """
    if not datos.categorias:
        # Sin categorías no hay nada que analizar, y preguntarle igual gastaría
        # una llamada para que conteste que no sabe.
        return []

    try:
        respuesta = _cliente.models.generate_content(
            model=MODELO,
            contents=_resumen_para_el_modelo(datos),
            config=types.GenerateContentConfig(
                system_instruction=_INSTRUCCION,
                response_mime_type="application/json",
                response_schema=Insights,
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
    except genai_errors.APIError as exc:
        logger.error("Gemini rechazó el pedido de insights: %s", exc)
        raise InsightsError("No pude analizar tus gastos ahora mismo.") from exc
    except Exception as exc:
        logger.exception("Error inesperado generando insights")
        raise InsightsError("No pude analizar tus gastos ahora mismo.") from exc

    resultado: Insights | None = respuesta.parsed
    if resultado is None:
        raise InsightsError("El análisis volvió vacío.")

    return resultado.insights[:MAX_INSIGHTS]
