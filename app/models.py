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
    REGISTRAR_VARIOS = "registrar_varios"
    REGISTRAR_INVERSION = "registrar_inversion"
    CERRAR_INVERSION = "cerrar_inversion"
    CREAR_ALERTA = "crear_alerta"
    VER_ALERTAS = "ver_alertas"
    SIMULAR_COMPRA = "simular_compra"
    COMPARAR_CUOTAS = "comparar_cuotas"
    CONSULTA_LIBRE = "consulta_libre"
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
    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    categoria: str = Field(min_length=1, max_length=60)
    descripcion: str = Field(min_length=1, max_length=60)
    comercio: str | None = Field(default=None, max_length=60)
    clave_item: str | None = Field(default=None, max_length=60)
    cantidad: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unidad: str | None = Field(default=None, max_length=20)
    precio_unitario: Decimal | None = Field(
        default=None, gt=0, max_digits=14, decimal_places=2
    )
    cuenta: str | None = Field(default=None, min_length=1, max_length=40)


class Inversion(BaseModel):
    """Una tenencia comprada: qué, cuánto y a qué precio."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: TipoInversion
    ticker: str | None = Field(default=None, max_length=20)
    nombre: str = Field(min_length=1, max_length=120)
    cantidad: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    precio_compra: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    moneda: Moneda = Moneda.USD
    fecha_compra: date
    sector: str | None = Field(default=None, max_length=60)


class TipoAlerta(str, Enum):
    """Qué tiene que pasar para que la alerta suene."""

    BAJA = "baja"
    SUBE = "sube"
    DEBAJO = "debajo"
    ENCIMA = "encima"


class Alerta(BaseModel):
    """Un umbral de precio que el usuario quiere que le avisen."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=20)
    mercado: str = Field(default="us", pattern="^(us|ar)$")
    tipo: TipoAlerta
    umbral: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class Agregacion(str, Enum):
    """Qué número se calcula sobre los movimientos que quedan tras filtrar."""

    TOTAL = "total"
    PROMEDIO = "promedio"
    MAXIMO = "maximo"
    MINIMO = "minimo"
    CANTIDAD = "cantidad"


class BasePromedio(str, Enum):
    """Promedio ¿de qué? "Gasto promedio" y "cuánto gasto por día" no son lo mismo."""

    MOVIMIENTO = "movimiento"
    DIA = "dia"
    MES = "mes"


class Dimension(str, Enum):
    """Por qué se agrupa el resultado. NINGUNA = un solo número."""

    NINGUNA = "ninguna"
    CATEGORIA = "categoria"
    COMERCIO = "comercio"
    DIA_SEMANA = "dia_semana"
    MES = "mes"
    TIPO = "tipo"
    MONEDA = "moneda"
    CUENTA = "cuenta"


class DiaSemana(str, Enum):
    LUNES = "lunes"
    MARTES = "martes"
    MIERCOLES = "miercoles"
    JUEVES = "jueves"
    VIERNES = "viernes"
    SABADO = "sabado"
    DOMINGO = "domingo"


class Periodo(BaseModel):
    """Un rango de fechas con el nombre que le da el usuario."""

    model_config = ConfigDict(str_strip_whitespace=True)

    desde: date | None = None
    hasta: date | None = None
    etiqueta: str = "en total"


class PlanConsulta(BaseModel):
    """Una pregunta analítica traducida a parámetros."""

    model_config = ConfigDict(str_strip_whitespace=True)

    agregacion: Agregacion = Agregacion.TOTAL
    base_promedio: BasePromedio = BasePromedio.MOVIMIENTO
    agrupar_por: Dimension = Dimension.NINGUNA

    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = Field(default=None, max_length=60)
    comercio: str | None = Field(default=None, max_length=60)
    dias_semana: tuple[DiaSemana, ...] = ()

    periodo: Periodo = Field(default_factory=Periodo)
    comparar_con: Periodo | None = None

    limite: int = Field(default=8, ge=1, le=50)


class CompraHipotetica(BaseModel):
    """Algo que el usuario está pensando comprar, y todavía no compró."""

    model_config = ConfigDict(str_strip_whitespace=True)

    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    que: str = Field(min_length=1, max_length=60)
    categoria: str | None = Field(default=None, max_length=60)


class Financiacion(BaseModel):
    """Una compra financiada a comparar contra su precio de contado."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cuotas: int = Field(gt=0, le=120)
    monto_cuota: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    precio_contado: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    que: str | None = Field(default=None, max_length=60)
    tasa_mensual: Decimal | None = Field(default=None, gt=0, lt=1)


class Consulta(BaseModel):
    """Los filtros de una pregunta, ya resueltos a valores concretos."""

    model_config = ConfigDict(str_strip_whitespace=True)

    desde: date | None = None
    hasta: date | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    etiqueta_periodo: str = "en total"
