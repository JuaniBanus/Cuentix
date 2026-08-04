"""Modelos de dominio validados con Pydantic."""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TipoMovimiento(str, Enum):
    """Naturaleza del movimiento. Determina el signo en los reportes."""

    GASTO = "gasto"
    INGRESO = "ingreso"
    INVERSION = "inversion"
    AHORRO = "ahorro"


class Moneda(str, Enum):
    ARS = "ARS"
    USD = "USD"
    EUR = "EUR"


class Intencion(str, Enum):
    """Qué quiso hacer el usuario con su mensaje."""

    REGISTRAR = "registrar"
    TOTAL_POR_TIPO = "total_por_tipo"
    TOTAL_POR_CATEGORIA = "total_por_categoria"
    BALANCE = "balance"
    DESCONOCIDA = "desconocida"


class Movimiento(BaseModel):
    """Un gasto, ingreso, inversión o ahorro registrado por el usuario."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    fecha: date
    tipo: TipoMovimiento
    # gt=0: el monto siempre es positivo; el signo lo aporta `tipo`.
    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    categoria: str = Field(min_length=1, max_length=60)
    # Etiqueta corta generada por el parser ("pancho y coca"), NO el mensaje
    # del usuario: esa frase se usa en memoria para extraer el movimiento y se
    # descarta. El tope de 60 es el mismo que el de categoria, porque ahora
    # son dos etiquetas del mismo orden y no un texto libre.
    descripcion: str = Field(min_length=1, max_length=60)


class Consulta(BaseModel):
    """Los filtros de una pregunta, ya resueltos a valores concretos.

    Todos los filtros son opcionales: `None` significa "sin restricción".
    Un rango de fechas en None abarca todo el historial, que es lo correcto
    para preguntas como "¿cuánto llevo ahorrado?".
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    desde: date | None = None
    hasta: date | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    # Texto para armar la respuesta: "este mes", "en julio", "en total".
    etiqueta_periodo: str = "en total"
