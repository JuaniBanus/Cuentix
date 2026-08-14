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
    # Varios movimientos en un solo mensaje ("gasté 5 lucas en el súper, 2 en
    # un café y cargué 30 de nafta"). Va aparte de REGISTRAR porque el camino
    # es distinto: se guarda en lote, algunos ítems pueden quedar en duda sin
    # frenar a los demás, y la confirmación es un resumen y no una línea.
    REGISTRAR_VARIOS = "registrar_varios"
    REGISTRAR_INVERSION = "registrar_inversion"
    CREAR_ALERTA = "crear_alerta"
    VER_ALERTAS = "ver_alertas"
    # Pregunta analítica libre, resuelta con un PlanConsulta. Cubre todo lo
    # que las tres intenciones de abajo no alcanzan: agrupar por día de la
    # semana o comercio, promedios, máximos y comparaciones entre períodos.
    # Una compra que TODAVÍA NO PASÓ y el usuario está pensando. No se
    # registra nada: se analiza y se le devuelve su situación para que decida.
    SIMULAR_COMPRA = "simular_compra"
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


class TipoAlerta(str, Enum):
    """Qué tiene que pasar para que la alerta suene.

    baja/sube miden un porcentaje contra el precio que había cuando se creó;
    debajo/encima comparan contra un precio fijo. Son cuatro casos y no dos con
    signo: "baja 5%" y "sube -5%" serían la misma cosa escrita de dos formas.
    """

    BAJA = "baja"
    SUBE = "sube"
    DEBAJO = "debajo"
    ENCIMA = "encima"


class Alerta(BaseModel):
    """Un umbral de precio que el usuario quiere que le avisen."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=20)
    # "us" (NASDAQ/NYSE) o "ar" (BYMA). Sin esto, una alerta sobre AAPL podría
    # vigilar el CEDEAR cuando se quiso la acción, o al revés.
    mercado: str = Field(default="us", pattern="^(us|ar)$")
    tipo: TipoAlerta
    # Porcentaje o precio según el tipo, siempre positivo.
    umbral: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


# --------------------------------------------------------------------------
# Plan de consulta analítica
#
# Este bloque es el vocabulario CERRADO con el que se pueden expresar las
# preguntas libres. Gemini no escribe SQL ni nombres de columna: elige valores
# de estos enums. Lo que no está acá, no se puede pedir.
# --------------------------------------------------------------------------


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
    """Una pregunta analítica traducida a parámetros.

    Es la ÚNICA forma en que una pregunta llega a la base. Cada campo es un
    enum, una fecha o un texto que solo se usa como VALOR de un filtro, nunca
    como nombre de columna ni como fragmento de consulta.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    agregacion: Agregacion = Agregacion.TOTAL
    base_promedio: BasePromedio = BasePromedio.MOVIMIENTO
    agrupar_por: Dimension = Dimension.NINGUNA

    # Filtros. None = sin restringir por eso.
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = Field(default=None, max_length=60)
    # Texto libre que se busca DENTRO de la descripción. Se pasa como valor
    # a un ilike con los comodines escapados; nunca se concatena a una query.
    comercio: str | None = Field(default=None, max_length=60)
    dias_semana: tuple[DiaSemana, ...] = ()

    periodo: Periodo = Field(default_factory=Periodo)
    # Si viene, la respuesta compara los dos períodos. Son DOS consultas
    # separadas y una resta en Python, no una subconsulta.
    comparar_con: Periodo | None = None

    # Cuántos grupos mostrar cuando se agrupa. Techo duro en analitica.py.
    limite: int = Field(default=8, ge=1, le=50)


class CompraHipotetica(BaseModel):
    """Algo que el usuario está pensando comprar, y todavía no compró.

    No tiene fecha ni se guarda en ningún lado: existe solo el tiempo que dura
    la respuesta. Es la diferencia entera con un Movimiento.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    # Qué es, con las palabras del usuario ("zapatillas", "un viaje a Brasil").
    que: str = Field(min_length=1, max_length=60)
    # Para poder comparar contra lo que ya gasta en ese rubro.
    categoria: str | None = Field(default=None, max_length=60)


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
