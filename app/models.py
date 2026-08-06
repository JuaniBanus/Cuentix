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


class TipoInversion(str, Enum):
    """Clase de activo. Coincide con el check de la tabla `inversiones`."""

    ACCION = "accion"
    ETF = "etf"
    BONO = "bono"
    CEDEAR = "cedear"
    FCI = "fci"
    CRIPTO = "cripto"
    PLAZO_FIJO = "plazo_fijo"


class Intencion(str, Enum):
    """Qué quiso hacer el usuario con su mensaje."""

    REGISTRAR = "registrar"
    REGISTRAR_INVERSION = "registrar_inversion"
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
    # Dónde está la plata: "efectivo", "banco", "billetera virtual".
    #
    # None significa que el usuario no lo dijo, y es un valor legítimo: la
    # mayoría de los mensajes no lo mencionan. El parser nunca lo deduce, así
    # que un null acá quiere decir "no se sabe" y no "no tiene".
    #
    # Es distinto de `categoria`: en "puse 100 lucas en un plazo fijo del
    # banco", la categoría es "plazo fijo" y la cuenta es "banco".
    cuenta: str | None = Field(default=None, min_length=1, max_length=40)


class Inversion(BaseModel):
    """Una tenencia comprada: qué, cuánto y a qué precio.

    Espeja la tabla `inversiones`. `user_id` no está acá: lo agrega db.py al
    insertar, porque sale de la configuración y no del mensaje del usuario.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: TipoInversion
    # AAPL, BTC, AL30. Un plazo fijo puede no tener ticker.
    ticker: str | None = Field(default=None, max_length=20)
    nombre: str = Field(min_length=1, max_length=120)
    # 8 decimales: 0.00000001 BTC tiene que sobrevivir. Es la misma precisión
    # que numeric(24,8) en la tabla.
    cantidad: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    precio_compra: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    # Default USD y no ARS: las tenencias se cotizan casi siempre en dólares.
    moneda: Moneda = Moneda.USD
    fecha_compra: date
    sector: str | None = Field(default=None, max_length=60)


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
