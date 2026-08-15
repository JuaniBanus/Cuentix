"""Narrativa mensual: el resumen en prosa de cómo fue el mes.

Mismo criterio de privacidad que app/insights.py, y por el mismo motivo: a
Gemini viajan NÚMEROS YA CALCULADOS, nunca movimientos crudos ni las
descripciones que escribió el usuario. Un total por categoría no identifica a
nadie; "pizza con Marina el viernes" sí. Los agregados los arma el navegador,
que es donde ya están los datos, y acá solo se los redacta.

EL TONO
Cálido, rioplatense, en segunda persona. Y sobre todo: NO moralista. Es la
misma regla que el asesor de compras y por la misma razón —un resumen que
reta se deja de leer al segundo mes— pero acá hay un riesgo extra: la prosa
invita a opinar mucho más que una lista de números. Por eso el prompt prohíbe
explícitamente felicitar, retar y aconsejar, y pide describir.

LO QUE NO PUEDE HACER
Inventar cifras. Si un dato no está en los agregados, no existe: no se estima,
no se redondea "más o menos" y no se completa con lo que suene bien. Un número
inventado dentro de un texto que suena confiado es peor que no tener el texto.
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

# Suficiente para tres o cuatro párrafos. Más que eso deja de leerse.
LARGO_MAXIMO = 1400

_cliente = genai.Client(api_key=GEMINI_API_KEY)


class NarrativaError(RuntimeError):
    """No se pudo generar el resumen del mes."""


class CategoriaMes(BaseModel):
    nombre: str = Field(max_length=60)
    total: Decimal
    # Contra el promedio propio del usuario, en porcentaje. None = sin historia.
    variacion_vs_promedio_pct: float | None = None


class ObjetivoMes(BaseModel):
    nombre: str = Field(max_length=80)
    porcentaje: int
    aportado_en_el_mes: Decimal | None = None


class AgregadosMes(BaseModel):
    """Todo lo que el resumen necesita. Nada de esto identifica a nadie."""

    mes: str = Field(max_length=40, description="Cómo nombrarlo: «julio», «agosto»")
    moneda: str = Field(max_length=3)

    total_gastado: Decimal
    total_ingresado: Decimal | None = None
    total_ahorrado: Decimal | None = None

    # Contra el propio promedio del usuario, nunca contra otras personas.
    gasto_promedio_meses_previos: Decimal | None = None
    meses_de_historia: int = 0
    tasa_ahorro_pct: float | None = None
    tasa_ahorro_promedio_pct: float | None = None

    categorias: list[CategoriaMes] = Field(default_factory=list, max_length=12)
    objetivos: list[ObjetivoMes] = Field(default_factory=list, max_length=6)

    # Del termómetro, si se pudo calcular.
    inflacion_personal_pct: float | None = None
    # Cargos recurrentes detectados y cuánto pesan por mes.
    recurrentes_total: Decimal | None = None
    recurrentes_cantidad: int = 0


_INSTRUCCION = """\
Escribís el resumen mensual de las finanzas de una persona, para que lo lea
ella misma en su app. Español rioplatense, segunda persona (vos), cálido y
directo, como se lo contarías a un amigo que te pidió que le mires las cuentas.

FORMATO
- Dos o tres párrafos cortos. Prosa corrida, sin títulos, sin viñetas y sin
  emojis.
- Máximo 200 palabras.
- Los montos van tal como te los paso, con su símbolo. No los redondees ni los
  reformatees.

QUÉ CONTAR
Empezá por lo que más se movió, no por el total: el total ya lo tiene arriba en
la pantalla. Si algo cambió mucho contra su propio promedio, ese es el tema del
resumen. Cerrá con los objetivos si los hay.

REGLAS QUE NO SE NEGOCIAN

1. NO INVENTES NINGÚN NÚMERO. Solo podés usar las cifras que están en los
   datos. Si algo no está, no lo menciones. Nada de "aproximadamente",
   "cerca de" ni estimaciones propias.

2. NO FELICITES NI RETES. Nada de "¡excelente mes!", "te felicito", "ojo con
   los gastos", "deberías", "te conviene", "la próxima tratá de". Describí lo
   que pasó y dejá que la persona saque su conclusión. Un mes con mucho gasto
   puede ser un mes con una mudanza, y vos no sabés.

3. NO COMPARES CON OTRAS PERSONAS. Ni con promedios del país, ni con "lo
   normal", ni con "la mayoría". La única comparación válida es contra su
   propio historial, y solo si te lo paso.

4. NO ACONSEJES. No cierres con recomendaciones ni con planes para el mes que
   viene. El resumen describe lo que pasó y termina.

5. Si hay poca historia, decilo con naturalidad ("todavía tengo pocos meses
   para comparar") en vez de sacar conclusiones de dos datos.

Escribí solo el texto del resumen, sin encabezado ni comillas."""


def _datos_para_el_modelo(datos: AgregadosMes) -> str:
    """Los agregados como texto plano, en el orden en que importan."""
    m = datos.moneda
    lineas = [f"MES: {datos.mes}", f"MONEDA: {m}", f"Gastado: {datos.total_gastado}"]

    if datos.total_ingresado is not None:
        lineas.append(f"Ingresado: {datos.total_ingresado}")
    if datos.total_ahorrado is not None:
        lineas.append(f"Ahorrado: {datos.total_ahorrado}")

    if datos.gasto_promedio_meses_previos is not None and datos.meses_de_historia:
        lineas.append(
            f"Su propio promedio de gasto en los {datos.meses_de_historia} meses "
            f"previos: {datos.gasto_promedio_meses_previos}"
        )
    else:
        lineas.append("No hay suficientes meses previos para comparar.")

    if datos.tasa_ahorro_pct is not None:
        texto = f"Tasa de ahorro del mes: {datos.tasa_ahorro_pct:.0f}% de lo que entró"
        if datos.tasa_ahorro_promedio_pct is not None:
            texto += f" (su promedio: {datos.tasa_ahorro_promedio_pct:.0f}%)"
        lineas.append(texto)

    if datos.categorias:
        lineas.append("\nPor categoría (de mayor a menor):")
        for c in datos.categorias:
            fila = f"- {c.nombre}: {c.total}"
            if c.variacion_vs_promedio_pct is not None:
                signo = "+" if c.variacion_vs_promedio_pct > 0 else ""
                fila += f" ({signo}{c.variacion_vs_promedio_pct:.0f}% vs su promedio)"
            lineas.append(fila)

    if datos.objetivos:
        lineas.append("\nObjetivos de ahorro:")
        for o in datos.objetivos:
            fila = f"- {o.nombre}: {o.porcentaje}% completado"
            if o.aportado_en_el_mes is not None:
                fila += f", aportó {o.aportado_en_el_mes} este mes"
            lineas.append(fila)

    if datos.inflacion_personal_pct is not None:
        lineas.append(
            f"\nInflación de su propia canasta: {datos.inflacion_personal_pct:.1f}% mensual"
        )

    if datos.recurrentes_cantidad:
        lineas.append(
            f"Gastos recurrentes detectados: {datos.recurrentes_cantidad}, "
            f"{datos.recurrentes_total} por mes"
        )

    return "\n".join(lineas)


def generar(datos: AgregadosMes) -> str:
    """El texto del resumen. Lanza NarrativaError si no se pudo."""
    try:
        respuesta = _cliente.models.generate_content(
            model=MODELO,
            contents=_datos_para_el_modelo(datos),
            config=types.GenerateContentConfig(
                system_instruction=_INSTRUCCION,
                # Sin response_schema: acá se quiere prosa, no un objeto. Es la
                # diferencia con el resto del parser, donde la estructura es lo
                # que importa.
                temperature=0.4,  # algo de aire para que no suene a plantilla
                max_output_tokens=600,
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
    except genai_errors.APIError as exc:
        logger.exception("Falló la generación de la narrativa")
        raise NarrativaError(
            f"No pude escribir el resumen (error {exc.code}). Probá en un rato."
        ) from exc
    except Exception as exc:
        logger.exception("Error inesperado generando la narrativa")
        raise NarrativaError("No pude escribir el resumen del mes.") from exc

    texto = (respuesta.text or "").strip()
    if not texto:
        raise NarrativaError("El resumen salió vacío.")

    # Recorte duro: el prompt pide 200 palabras, pero es un pedido y no una
    # garantía. Se corta en el último punto para no dejar la frase colgada.
    if len(texto) > LARGO_MAXIMO:
        recortado = texto[:LARGO_MAXIMO]
        corte = recortado.rfind(".")
        texto = (recortado[: corte + 1] if corte > 200 else recortado).strip()

    return texto
