"""Interpretación de texto libre con Gemini.

Un mismo mensaje puede ser dos cosas distintas: un registro ("me gasté 8 lucas
en el super") o una pregunta ("¿cuánto gasté este mes?"). `interpretar_mensaje`
resuelve ambas en UNA sola llamada: el modelo devuelve la intención y, según
cuál sea, el movimiento a guardar o los filtros de la consulta.

Una sola llamada y no dos (clasificar → extraer) porque cuesta y tarda la
mitad, y porque el modelo decide la intención viendo el mensaje completo.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import GEMINI_API_KEY
from app.models import (
    Agregacion,
    Alerta,
    BasePromedio,
    CompraHipotetica,
    Consulta,
    DiaSemana,
    Dimension,
    Intencion,
    Inversion,
    Moneda,
    Movimiento,
    Periodo,
    PlanConsulta,
    TipoAlerta,
    TipoInversion,
    TipoMovimiento,
)

logger = logging.getLogger(__name__)

MODELO = "gemini-3.5-flash-lite"

# Cliente único a nivel módulo: reutiliza la conexión HTTP entre mensajes.
_cliente = genai.Client(api_key=GEMINI_API_KEY)


class ParserError(RuntimeError):
    """No se pudo interpretar el texto."""


# Los tres modelos siguientes son el esquema que le pedimos a Gemini. Son
# distintos de los de models.py a propósito:
#
# 1. El tipo Schema de la API de Gemini no acepta restricciones numéricas
#    (`gt` / `exclusiveMinimum`) ni el `anyOf` que Pydantic genera para
#    `Decimal`. Acá usamos `float` sin restricciones, y la validación fuerte
#    (monto > 0, decimales, longitudes) la aplica `Movimiento` al construir
#    el objeto final.
# 2. `descripcion` sí está, y es a propósito: antes guardábamos el mensaje
#    literal del usuario, y esa frase quedaba en la base para siempre sin que
#    nada la leyera. Ahora el modelo devuelve una etiqueta corta, que es la
#    parte útil sin arrastrar cómo lo escribió.
#
# Ojo: el docstring de una clase viajaría a la API como `description` del
# schema, por eso las notas van como comentario.
class _MovimientoExtraido(BaseModel):
    fecha: date
    tipo: TipoMovimiento
    monto: float
    moneda: Moneda = Moneda.ARS
    categoria: str
    descripcion: str
    # Opcional de verdad: el modelo tiene que poder no contestarla. Si fuera
    # `str` con default "", el schema la pediría igual y el modelo llenaría el
    # hueco con lo primero que le suene.
    cuenta: str | None = None
    # PARA QUÉ se aparta la plata, cuando el usuario nombra una meta. No es una
    # columna: es el texto con el que después se busca el objetivo.
    objetivo: str | None = None


class _ConsultaExtraida(BaseModel):
    desde: date | None = None
    hasta: date | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    etiqueta_periodo: str | None = None


# Todo opcional salvo el tipo: una compra mal contada ("compré bitcoin") tiene
# que poder volver con los huecos marcados, para preguntar en vez de inventar.
class _InversionExtraida(BaseModel):
    tipo: TipoInversion | None = None
    ticker: str | None = None
    nombre: str | None = None
    cantidad: float | None = None
    precio_compra: float | None = None
    moneda: Moneda | None = None
    fecha_compra: date | None = None
    sector: str | None = None


class _AlertaExtraida(BaseModel):
    ticker: str | None = None
    mercado: str | None = None
    tipo: TipoAlerta | None = None
    umbral: float | None = None


# Un ítem de una lista de varios movimientos. TODO opcional, incluso lo que en
# `_MovimientoExtraido` es obligatorio: en "gasté 5 lucas en el súper y 2 en un
# café", el "2" puede ser 2.000 o 2 pesos y no hay forma de saberlo. El ítem
# tiene que poder volver incompleto y con la duda escrita, para preguntar por
# ese solo sin frenar a los demás.
class _MovimientoItem(BaseModel):
    fecha: date | None = None
    tipo: TipoMovimiento | None = None
    monto: float | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    descripcion: str | None = None
    cuenta: str | None = None
    # El pedazo del mensaje del que salió este ítem, para poder citarlo al
    # preguntar. Sin esto, "no entendí el segundo" no le dice nada a nadie.
    fragmento: str | None = None
    # Qué quedó sin resolver, en una frase corta y en segunda persona. null si
    # el ítem está completo.
    duda: str | None = None


class _PeriodoExtraido(BaseModel):
    desde: date | None = None
    hasta: date | None = None
    etiqueta: str | None = None


# El vocabulario de las preguntas libres. Cada campo es un enum cerrado o un
# valor de filtro: el modelo no puede nombrar una columna ni escribir una
# condición. Lo que no esté acá, no se puede pedir.
class _PlanExtraido(BaseModel):
    agregacion: Agregacion | None = None
    base_promedio: BasePromedio | None = None
    agrupar_por: Dimension | None = None
    tipo: TipoMovimiento | None = None
    moneda: Moneda | None = None
    categoria: str | None = None
    comercio: str | None = None
    dias_semana: list[DiaSemana] | None = None
    periodo: _PeriodoExtraido | None = None
    comparar_con: _PeriodoExtraido | None = None
    limite: int | None = None


class _CompraExtraida(BaseModel):
    monto: float | None = None
    moneda: Moneda | None = None
    que: str | None = None
    categoria: str | None = None


class _InterpretacionExtraida(BaseModel):
    intencion: Intencion
    movimiento: _MovimientoExtraido | None = None
    movimientos: list[_MovimientoItem] | None = None
    plan: _PlanExtraido | None = None
    compra: _CompraExtraida | None = None
    consulta: _ConsultaExtraida | None = None
    inversion: _InversionExtraida | None = None
    alerta: _AlertaExtraida | None = None


class Interpretacion(NamedTuple):
    """Resultado de interpretar un mensaje: qué quiso hacer y con qué datos."""

    intencion: Intencion
    movimiento: Movimiento | None = None
    # Los ítems de un mensaje con varios movimientos que quedaron completos.
    movimientos: list[Movimiento] = ()
    # Los que no: (fragmento citado, qué falta preguntar).
    dudas: tuple[tuple[str, str], ...] = ()
    plan: PlanConsulta | None = None
    # Una compra que el usuario está pensando. No se guarda: se analiza.
    compra: CompraHipotetica | None = None
    consulta: Consulta | None = None
    inversion: Inversion | None = None
    alerta: Alerta | None = None
    # A qué objetivo dijo el usuario que va el ahorro, con sus palabras. Viaja
    # aparte del Movimiento porque no es un dato de la tabla: es la pista para
    # buscar el objetivo, y puede no encontrar ninguno.
    objetivo: str | None = None
    # Campos que la compra necesita y el mensaje no traía. Si tiene algo,
    # `inversion` viene en None y hay que preguntar en vez de guardar.
    faltantes: tuple[str, ...] = ()


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _instruccion_sistema(hoy: date) -> str:
    """Prompt de sistema. Recibe la fecha para resolver referencias relativas."""
    ayer = hoy - timedelta(days=1)
    # `strftime('%A')` devolvería el día en inglés según el locale del proceso.
    dia = _DIAS[hoy.weekday()]
    inicio_mes = hoy.replace(day=1)
    return f"""\
Sos un asistente de finanzas personales. El usuario es argentino y escribe en
español rioplatense, de forma coloquial y abreviada.

Cada mensaje es una de dos cosas, y tu primera tarea es decidir cuál:

- REGISTRAR: el usuario está anotando algo que pasó.
  "me gasté 8 lucas en el super", "cobré el sueldo", "puse 500 dólares en cripto".
- CONSULTAR: el usuario pregunta por datos que ya cargó.
  "¿cuánto gasté este mes?", "cuánto llevo ahorrado", "en qué se me va la plata".

Señales de consulta: signos de pregunta, "cuánto", "cuánta", "qué", "cómo vengo",
"en qué", "mostrame", "decime", "total de", verbos en pretérito perfecto
compuesto sin un monto concreto. Si el mensaje trae un monto explícito, casi
siempre es un registro.

FECHA DE HOY: {hoy.isoformat()}, {dia}. Ayer fue {ayer.isoformat()}.
El mes en curso arranca el {inicio_mes.isoformat()}.

=========================== SI ES UN REGISTRO ===========================
Poné intencion="registrar" y completá "movimiento". Dejá "consulta" en null.

MONTOS
- Interpretá la jerga: luca=1.000, palo=1.000.000, gamba=100.
  "8 lucas" = 8000, "300 mil" = 300000, "un millón y medio" = 1500000,
  "2 palos" = 2000000.
- Formato argentino: el punto separa miles y la coma decimales.
  "15.340,50" = 15340.50. Devolvé un número plano, sin separadores ni símbolo.
- El monto es siempre positivo. El signo lo determina el campo "tipo".

MONEDA
- Si no se aclara, asumí ARS.
- Usá USD si se menciona: "dólares", "usd", "u$s", "verdes", "billetes", "blue",
  "mep". "Palos verdes" son millones de dólares.
- Usá EUR si se menciona: "euros", "eur", "€".
  "gasté 200 euros" -> 200 EUR. "€150" -> 150 EUR. "150 eur" -> 150 EUR.
- El símbolo "$" solo, sin más aclaración, es ARS: en Argentina "$" son pesos.
  Solo es USD si además dice "dólares", "verdes" o similar.
- La jerga de montos (luca, palo, gamba) vale para cualquier moneda:
  "2 lucas de euros" = 2000 EUR.

TIPO (elegí exactamente uno)
- gasto: plata que sale y no vuelve. Compras, servicios, comida, transporte,
  alquiler, impuestos, salidas.
- ingreso: plata que entra. Sueldo, cobros, ventas, honorarios.
- ahorro: plata que se guarda y sigue siendo tuya, sin riesgo. Plazo fijo,
  guardar en el cajón, pasar a la caja de ahorro, "aparté para".
- inversion: plata puesta a buscar rendimiento asumiendo riesgo. Comprar
  dólares, acciones, CEDEARs, cripto, fondos comunes, bonos.
Ante la duda entre ahorro e inversion, preguntate si puede perder valor:
si puede, es inversion.

FECHA
- Resolvé referencias relativas contra la FECHA DE HOY: "ayer", "anteayer",
  "el lunes" (el lunes más reciente ya pasado), "hace una semana",
  "el 3" (el día 3 del mes en curso, o del mes pasado si todavía no llegó).
- Si el mensaje no menciona fecha, usá la fecha de hoy.
- Nunca devuelvas una fecha futura.

CATEGORIA
- Una o dos palabras, en minúsculas, sin tildes ni signos.
- Reutilizá etiquetas comunes: supermercado, comida, transporte, alquiler,
  servicios, salud, educacion, ocio, ropa, sueldo, freelance, dolares,
  cripto, plazo fijo, otros.
- Si nada encaja, usá "otros".

CUENTA (dónde está la plata)
- Completala SOLO si el mensaje dice dónde quedó, de dónde salió o a dónde fue
  la plata: "guardé 50 lucas en el banco" -> banco, "aparté efectivo" ->
  efectivo, "lo puse en Mercado Pago" -> billetera virtual, "50 mil al cajón"
  -> efectivo.
- Si el mensaje NO lo dice, dejala en null. Nunca la deduzcas del tipo, de la
  categoría ni de lo habitual: un null es la respuesta correcta cuando el
  usuario no lo mencionó, y es mejor que un lugar inventado.
  "aparté 50 mil para el viaje" -> cuenta=null. "gasté 8 lucas en el super"
  -> cuenta=null.
- No la confundas con la categoría, que es PARA QUE es la plata:
  "puse 100 lucas en un plazo fijo del banco" -> categoria="plazo fijo",
  cuenta="banco". "hice un plazo fijo" -> categoria="plazo fijo", cuenta=null.
- Etiquetas preferidas: efectivo, banco, billetera virtual, caja de seguridad,
  broker, cripto. Si nombran una marca o un producto, usá la etiqueta general:
  mercado pago / ualá / prex / naranja x -> billetera virtual;
  caja de ahorro / cuenta sueldo / homebanking / nombre de un banco -> banco;
  binance / lemon / buenbit -> cripto; cocos / iol / balanz -> broker;
  el cajón / abajo del colchón / la lata -> efectivo.
- Si no encaja en ninguna, usá una o dos palabras en minúsculas y sin tildes.

OBJETIVO (para qué se aparta la plata)
- SOLO para tipo=ahorro, y solo si el mensaje nombra una meta concreta:
  "guardé 150 mil para el viaje a Europa" -> objetivo="viaje a Europa"
  "aparté 50 lucas para el auto" -> objetivo="auto"
  "puse 20 mil para la casa" -> objetivo="casa"
- Devolvé el nombre de la meta tal como la nombró el usuario, SIN "para",
  "el", "la" ni el verbo. No inventes ni completes: si dijo "el auto",
  poné "auto", no "auto nuevo".
- En cualquier otro caso, null. Que un gasto o un ingreso tengan un motivo no
  los convierte en un objetivo: "gasté 8 lucas en el super" -> null,
  "cobré el sueldo" -> null.
- Ahorrar sin decir para qué también es null: "aparté 50 lucas" -> null,
  "guardé plata en el banco" -> null.
- No lo confundas con la cuenta, que es DÓNDE está la plata:
  "guardé 50 mil en el banco para el viaje" -> cuenta="banco",
  objetivo="viaje".

DESCRIPCION
- Una etiqueta de 2 a 5 palabras que diga QUE se compró o de dónde salió la
  plata, para distinguir dos movimientos de la misma categoría el mismo día.
  "pancho y coca", "sueldo agosto", "nafta", "cena con amigos", "plazo fijo".
- En minúsculas, sin tildes ni signos. Máximo 60 caracteres.
- NO copies la frase del usuario ni la parafrasees entera: es una etiqueta,
  no un resumen. Nada de montos, fechas ni verbos conjugados.
- NO incluyas datos personales: ni nombres propios, ni apodos, ni direcciones,
  ni comentarios sobre personas. "el regalo para Sofía" -> "regalo".
  "le pagué a mi psicóloga" -> "sesion".
- Si el mensaje no dice qué fue, repetí la categoría.

=================== SI SON VARIOS MOVIMIENTOS EN UN MENSAJE ==============
Poné intencion="registrar_varios" y completá la lista "movimientos", un
elemento por cada cosa que pasó. Dejá "movimiento" en null.

Esto es lo que la gente hace al final del día:
  "gasté 5 lucas en el súper, 2 en un café y cargué 30 de nafta"
  "hoy: 12 mil de farmacia, 8 de almuerzo y cobré 50 de un laburito"

CUÁNDO ES UNO Y CUÁNDO SON VARIOS
- Un solo hecho, aunque tenga varias frases -> registrar (singular).
  "gasté 8 lucas en el súper de Palermo con la tarjeta" es UNO.
- Dos o más hechos con su propio monto -> registrar_varios.
- Si son varios, van TODOS en la lista, incluso los de distinto tipo:
  un mensaje puede traer dos gastos y un ingreso.

CADA ÍTEM
- Las mismas reglas de montos, moneda, tipo, fecha y categoría de arriba.
- descripcion: la etiqueta corta de ESE ítem ("café", "nafta"), no del mensaje.
- fragmento: el pedacito del mensaje del que sacaste el ítem, copiado tal cual
  ("2 en un café"). Sirve para poder citarlo si hay que preguntar.
- La fecha se hereda: si el mensaje dice "ayer" una sola vez al principio,
  vale para todos los ítems.

MONTOS ABREVIADOS EN CADENA
Cuando el usuario enumera, suele decir la unidad una sola vez:
  "5 lucas en el súper, 2 en un café"  -> el "2" son 2.000, arrastra "lucas".
Aplicá ese arrastre SOLO cuando el número desnudo es del mismo orden y viene
en la misma enumeración. Si el arrastre da un monto absurdo para el rubro
—"30 de nafta" son 30.000, no 30 pesos ni 30 millones—, elegí el orden que
tenga sentido y NO marques duda.

DUDA: PREGUNTAR POR UNO SIN FRENAR A LOS DEMÁS
Si de un ítem no podés sacar el monto, o el número admite dos lecturas
razonables y ninguna es claramente la buena, dejá "monto" en null y escribí
en "duda" qué necesitás, en una frase corta y tuteando:
  duda: "¿los 2 del café son 2 mil o 2 pesos?"
Los demás ítems del mismo mensaje se completan igual: la duda de uno NUNCA
vacía a los otros. Un ítem con duda no lleva monto inventado.
No uses "duda" para lo que se puede deducir: la categoría siempre se puede
elegir, y ante la duda es "otros".

====================== SI ES UNA COMPRA DE INVERSIÓN =====================
Poné intencion="registrar_inversion" y completá "inversion". El resto en null.

Esto es distinto de un movimiento de tipo "inversion". Un movimiento anota
que salió plata ("puse 500 dólares en cripto"). Una COMPRA anota qué activo
entró a la cartera, con cantidad y precio unitario, y por eso se puede seguir
su ganancia después. Elegí registrar_inversion cuando el mensaje nombra un
activo concreto Y una cantidad:
  "compré 10 CEDEARs de Apple a US$25"
  "invertí en 0.5 BTC a 60000 USD"
  "me compré 100 AL30 a 1200 pesos"

CAMPOS
- tipo: accion, etf, bono, cedear, fci, cripto o plazo_fijo.
  Un CEDEAR es un cedear aunque el subyacente sea una acción (Apple, Tesla).
  Bitcoin, ethereum, USDT y demás son cripto. AL30/GD30/BOPREAL son bonos.
- ticker: el símbolo en MAYÚSCULAS, sin espacios. Deducilo del nombre cuando
  sea inequívoco: Apple->AAPL, Bitcoin->BTC, Ethereum->ETH, Tesla->TSLA,
  Mercado Libre->MELI, Google->GOOGL, Amazon->AMZN, Microsoft->MSFT.
  Si no lo sabés con certeza, dejalo en null: es preferible vacío a inventado.
- nombre: cómo lo diría una persona ("Apple", "Bitcoin", "Plazo fijo Galicia").
- cantidad: cuántas unidades. Acepta decimales (0.5 BTC).
- precio_compra: precio por UNIDAD, no el total. "10 a US$25" -> 25, no 250.
  Si el mensaje da solo el total ("puse 250 dólares en 10 cedears"), dividí:
  250/10 = 25.
- moneda: del PRECIO. "US$25" o "25 dólares" -> USD. "1200 pesos" -> ARS.
  "€30" -> EUR. Si no se aclara y el activo es cripto o CEDEAR, asumí USD;
  si es un bono argentino o un plazo fijo, asumí ARS.
- fecha_compra: como en los movimientos. Sin fecha, la de hoy.
- sector: solo si el mensaje lo menciona; si no, null.

DATOS FALTANTES: NO LOS INVENTES
Si falta algo que no se puede deducir —típicamente el precio o la cantidad—,
igual poné intencion="registrar_inversion" y devolvé "inversion" con los
campos que sí tengas y los otros en null. Nunca rellenes un precio con una
cotización que creas saber ni una cantidad con un 1 por defecto: el sistema
se encarga de preguntar lo que falte.
Ejemplo: "compré bitcoin" -> tipo=cripto, ticker=BTC, nombre=Bitcoin,
cantidad=null, precio_compra=null.

======================= SI PIDE UNA ALERTA DE PRECIO =====================
Poné intencion="crear_alerta" y completá "alerta". El resto en null.
  "avisame si AAPL baja 5%"
  "tocame si el bitcoin sube 10%"
  "avisame cuando TSLA esté por debajo de 200 dólares"
  "alerta si GGAL supera los 8000 pesos"

CAMPOS
- ticker: el símbolo en MAYÚSCULAS. Mismas equivalencias que en las compras
  (Apple->AAPL, bitcoin->BTC).
- tipo: "baja" o "sube" cuando el mensaje habla de un PORCENTAJE de variación.
  "debajo" o "encima" cuando habla de un PRECIO concreto que se cruza.
    "baja 5%" -> tipo=baja, umbral=5
    "supera los 8000 pesos" -> tipo=encima, umbral=8000
- umbral: siempre POSITIVO. La dirección la da el tipo, nunca el signo.
  "baja 5%" -> 5, jamás -5.
- mercado: "ar" si el mensaje menciona pesos, el Merval, BYMA o un papel
  argentino (GGAL, YPFD, AL30). "us" en cualquier otro caso, que es el default.

Si el mensaje no dice el umbral ("avisame si AAPL baja"), igual poné
intencion="crear_alerta" con umbral=null: el sistema pregunta.

Si pide VER las alertas que tiene ("qué alertas tengo", "mostrame mis
alertas"), poné intencion="ver_alertas" y dejá todo lo demás en null.

================ SI ESTÁ PENSANDO UNA COMPRA QUE NO HIZO ================
Poné intencion="simular_compra" y completá "compra". El resto en null.

ESTA ES LA DISTINCIÓN MÁS IMPORTANTE DE TODO ESTE PROMPT.
Confundirla tiene dos costos feos y opuestos: registrar como gasto algo que no
pasó le ensucia los números, y analizar como hipótesis algo que ya compró le
hace perder el registro.

YA PASÓ -> registrar (o registrar_varios)
  Verbos en pasado y hechos consumados:
  "gasté 8 lucas en el súper" · "me compré unas zapatillas de 90 mil"
  "pagué la luz" · "compré 500 dólares" · "salió 40 mil"
  "me gasté" con "me" también es PASADO: es un pasado enfático, no un deseo.

TODAVÍA NO -> simular_compra
  Deseo, intención, duda o consulta sobre el futuro:
  "¿me compro unas zapatillas de 90 mil?" · "me quiero comprar una tele de 800 mil"
  "¿me lo puedo comprar?" · "estoy pensando en gastarme 200 mil en un curso"
  "quiero gastarme 50 mil en salir" · "¿me alcanza para un viaje de 1 palo?"
  "vale la pena gastar 300 mil en esto?" · "tengo ganas de comprarme X"

SEÑALES DE HIPÓTESIS
- Signo de pregunta sobre la compra misma ("¿me compro…?", "¿me alcanza…?").
- Verbos de deseo o duda: quiero, querría, me gustaría, estoy pensando,
  tengo ganas, vale la pena, me conviene, debería.
- Futuro o condicional: "me voy a comprar", "me compraría".
- Presente que en rioplatense es futuro: "¿me compro X?" NO es "compré X".

CAMPOS
- monto: el precio de lo que está pensando. Misma jerga y formato que siempre.
  Si NO hay monto, no uses simular_compra: sin precio no hay nada que analizar.
  Un "¿me compro unas zapatillas?" sin número es intencion="desconocida".
- moneda: como siempre, ARS si no se aclara.
- que: qué es, corto y con las palabras del usuario ("unas zapatillas",
  "una tele", "un viaje a Brasil"). Sin el precio adentro.
- categoria: el rubro al que caería si la hiciera, con las mismas etiquetas de
  siempre (ropa, tecnologia, ocio, viaje...). Sirve para comparar contra lo
  que ya gasta ahí. Si no encaja en ninguna, null.

==================== SI ES UNA PREGUNTA ANALÍTICA LIBRE ==================
Poné intencion="consulta_libre" y completá "plan". El resto en null.

Las tres intenciones de abajo (total_por_tipo, total_por_categoria, balance)
son atajos para las tres preguntas más comunes. Para CUALQUIER otra cosa
—promedios, máximos, días de la semana, comercios, comparaciones entre
períodos, "cuántas veces"— usá consulta_libre. Ante la duda, consulta_libre:
es más expresiva y contesta igual de bien las simples.

CÓMO SE ARMA EL PLAN
- agregacion: qué número quiere.
  total (por defecto) · promedio · maximo · minimo · cantidad
  "¿cuánto gasté?" -> total       "¿cuál fue mi gasto más grande?" -> maximo
  "¿cuánto gasto en promedio?" -> promedio   "¿cuántas veces?" -> cantidad
- base_promedio: solo si agregacion=promedio. movimiento (por defecto) · dia · mes
  "gasto promedio" -> movimiento (cuánto sale cada compra)
  "cuánto gasto por día" -> dia      "por mes" -> mes
- agrupar_por: cómo abrir el resultado.
  ninguna (un número solo) · categoria · comercio · dia_semana · mes · tipo ·
  moneda · cuenta
  "¿en qué gasto?" -> categoria      "¿qué día gasto más?" -> dia_semana
  "¿cómo vengo mes a mes?" -> mes    "¿dónde compro más?" -> comercio
- tipo / moneda: filtran. null = sin filtrar.
- categoria: el nombre exacto del rubro, si la pregunta lo nombra.
- comercio: texto a buscar DENTRO de la descripción del movimiento, cuando
  pregunta por un lugar o comercio ("¿cuánto gasté en Starbucks?" -> "starbucks").
  No lo uses para rubros generales: "supermercado" es categoria, no comercio.
- dias_semana: lista, solo si la pregunta los menciona ("los fines de semana"
  -> ["sabado", "domingo"]).
- periodo: desde/hasta y una etiqueta para nombrarlo en la respuesta.
  Sin fechas si la pregunta no acota el tiempo. Etiquetas: "este mes",
  "en julio", "este año", "en total", "la semana pasada".
- comparar_con: SOLO si la pregunta compara dos épocas. Es el período CONTRA
  el que se compara, con su etiqueta.
  "¿gasté más este mes que el pasado?" -> periodo = este mes,
  comparar_con = el mes pasado ("el mes pasado").
- limite: cuántos grupos mostrar. 8 salvo que pida "el top 3" o similar.

EJEMPLOS
"¿cuánto gasté en promedio por día este mes?"
  agregacion=promedio, base_promedio=dia, tipo=gasto, periodo=este mes
"¿qué día de la semana gasto más?"
  agregacion=total, agrupar_por=dia_semana, tipo=gasto
"¿cuál fue mi gasto más grande del año?"
  agregacion=maximo, tipo=gasto, periodo={{año en curso}}
"¿cuánto llevo gastado en el chino?"
  agregacion=total, tipo=gasto, comercio="chino"
"¿gasté más este mes que el pasado?"
  agregacion=total, tipo=gasto, periodo=este mes, comparar_con=el mes pasado
"¿cuántas veces salí a comer en julio?"
  agregacion=cantidad, tipo=gasto, categoria="comida", periodo=julio

=========================== SI ES UNA CONSULTA ==========================
Elegí la intención que corresponda, completá "consulta" y dejá
"movimiento" en null.

- total_por_tipo: cuánto suma una clase de movimiento.
  "¿cuánto gasté este mes?" -> tipo=gasto, desde={inicio_mes.isoformat()}, hasta={hoy.isoformat()}
  "¿cuánto llevo ahorrado en dólares?" -> tipo=ahorro, moneda=USD, sin fechas
  "¿cuánto cobré este año?" -> tipo=ingreso, desde={hoy.year}-01-01
- total_por_categoria: el desglose por rubro.
  "¿en qué se me va la plata?" -> tipo=gasto, período del mes en curso
  "¿cuánto gasté en supermercado?" -> tipo=gasto, categoria="supermercado"
- balance: cuánto entró menos cuánto salió.
  "¿cómo vengo este mes?", "¿me alcanzó?", "balance de julio"

FILTROS DE LA CONSULTA
- desde / hasta: rango de fechas en formato YYYY-MM-DD, ambos inclusive.
  Dejalos en null si la pregunta no acota el tiempo ("cuánto llevo ahorrado",
  "en total", "histórico"). NO inventes un rango si el usuario no lo pidió.
- Si la pregunta habla del mes sin aclarar cuál, usá el mes en curso.
- tipo, moneda, categoria: completalos solo si la pregunta los menciona.
  En null significa "sin filtrar por eso".
- etiqueta_periodo: cómo nombrar el período en la respuesta, en minúsculas.
  Ejemplos: "este mes", "en julio", "este año", "en total", "la semana pasada".

======================= SI NO ES NINGUNA DE LAS DOS =====================
Poné intencion="desconocida" con los dos objetos en null. Usalo para saludos,
charla suelta o mensajes que no se entienden. No fuerces un registro."""


# Lo que un modelo escribe cuando le pedimos null y contesta con palabras.
# Cualquiera de estas es un "no lo dijo", no el nombre de una cuenta.
_CUENTA_VACIA = frozenset(
    {
        "null",
        "none",
        "nada",
        "ninguna",
        "ninguno",
        "n/a",
        "na",
        "no aplica",
        "no especifica",
        "no especificado",
        "no especificada",
        "no menciona",
        "no mencionada",
        "sin especificar",
        "desconocida",
        "desconocido",
        "-",
    }
)


def _normalizar_cuenta(valor: str | None) -> str | None:
    """Deja la cuenta lista para guardar, o None si no hay nada que guardar.

    El prompt pide null cuando el usuario no dice dónde, pero un modelo a veces
    contesta "no especificado" en vez de un null de verdad. Eso entraría a la
    base como si fuera una cuenta más y ensuciaría cualquier agrupación futura,
    así que se filtra acá.
    """
    limpio = " ".join((valor or "").split()).lower()[:40].strip()
    if not limpio or limpio in _CUENTA_VACIA:
        return None
    return limpio


def _a_movimiento(extraido: _MovimientoExtraido) -> Movimiento:
    """Convierte la salida de Gemini en el Movimiento definitivo.

    No recibe el mensaje del usuario a propósito: la etiqueta la genera el
    modelo y el texto original no sale nunca de `interpretar_mensaje`.

    `Decimal(str(...))` y no `Decimal(float)`: convertir el float directo
    arrastraría la basura binaria (0.1 -> 0.1000000000000000055...).
    """
    try:
        monto = Decimal(str(extraido.monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ParserError(f"Gemini devolvió un monto inusable: {extraido.monto!r}") from exc

    categoria = extraido.categoria.strip().lower()

    # El prompt pide 2 a 5 palabras, pero es un pedido y no una garantía: si el
    # modelo se pasa de largo, recortamos en vez de dejar que Movimiento lance
    # ValidationError, porque eso costaría el movimiento entero. El split/join
    # colapsa saltos de línea y espacios repetidos.
    descripcion = " ".join(extraido.descripcion.split()).lower()[:60].strip()

    try:
        return Movimiento(
            fecha=extraido.fecha,
            tipo=extraido.tipo,
            monto=monto,
            moneda=extraido.moneda,
            categoria=categoria,
            # Si el modelo la devuelve vacía, la categoría es un detalle pobre
            # pero válido: mejor eso que perder el movimiento por un campo
            # que no se muestra en ninguna respuesta.
            descripcion=descripcion or categoria,
            cuenta=_normalizar_cuenta(extraido.cuenta),
        )
    except ValidationError as exc:
        # Típicamente: monto <= 0 o categoria vacía.
        raise ParserError(f"Gemini devolvió un movimiento inválido: {exc.errors()}") from exc


# Nombre técnico -> cómo pedírselo al usuario.
_ETIQUETA_FALTANTE = {
    "tipo": "qué tipo de activo es (acción, cedear, cripto, bono, fci, plazo fijo)",
    "nombre": "qué compraste",
    "cantidad": "cuántas unidades compraste",
    "precio_compra": "a qué precio por unidad",
}


def _decimal_limpio(valor: float) -> Decimal:
    """float -> Decimal sin ceros de relleno ni basura binaria.

    `Decimal(str(...))` y no `Decimal(float)`, que arrastraría la cola binaria
    a una columna de 8 decimales. El normalize saca los ceros sobrantes
    (10.0 -> 10) y el quantize deshace la notación científica que normalize
    produce con los enteros (10 -> 1E+1), que Postgres no debería tener que
    interpretar.
    """
    numero = Decimal(str(valor)).normalize()
    if numero == numero.to_integral_value():
        return numero.quantize(Decimal(1))
    return numero


def _a_inversion(
    extraida: _InversionExtraida | None, hoy: date
) -> tuple[Inversion | None, tuple[str, ...]]:
    """Arma la Inversion, o devuelve qué falta para poder armarla.

    Devuelve (inversion, faltantes). Si `faltantes` tiene algo, `inversion` es
    None: preferimos preguntar antes que guardar una tenencia a medias, que
    después arruinaría todos los cálculos de ganancia.
    """
    if extraida is None:
        return None, ("tipo", "nombre", "cantidad", "precio_compra")

    faltantes = [
        campo
        for campo in ("tipo", "nombre", "cantidad", "precio_compra")
        if getattr(extraida, campo) is None
    ]
    # Un precio de 0 solo tiene sentido en un plazo fijo o un airdrop; para el
    # resto es casi siempre el modelo rellenando un hueco.
    if (
        extraida.precio_compra == 0
        and extraida.tipo is not TipoInversion.PLAZO_FIJO
        and "precio_compra" not in faltantes
    ):
        faltantes.append("precio_compra")
    if extraida.cantidad is not None and extraida.cantidad <= 0:
        faltantes.append("cantidad")

    if faltantes:
        return None, tuple(dict.fromkeys(faltantes))

    ticker = (extraida.ticker or "").strip().upper().replace(" ", "") or None

    try:
        inversion = Inversion(
            tipo=extraida.tipo,
            ticker=ticker[:20] if ticker else None,
            nombre=" ".join(extraida.nombre.split())[:120],
            cantidad=_decimal_limpio(extraida.cantidad),
            precio_compra=_decimal_limpio(extraida.precio_compra),
            moneda=extraida.moneda or Moneda.USD,
            fecha_compra=extraida.fecha_compra or hoy,
            sector=(extraida.sector or "").strip()[:60] or None,
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        raise ParserError(f"Gemini devolvió una inversión inválida: {exc}") from exc

    return inversion, ()


def _a_alerta(extraida: _AlertaExtraida | None) -> tuple[Alerta | None, tuple[str, ...]]:
    """Arma la Alerta, o devuelve qué falta para poder armarla."""
    if extraida is None:
        return None, ("ticker", "umbral")

    faltantes = []
    ticker = (extraida.ticker or "").strip().upper().replace(" ", "")
    if not ticker:
        faltantes.append("ticker")
    # El umbral en 0 o negativo no es un umbral: el modelo pudo haber mandado
    # el signo de la dirección, que acá lo aporta el tipo.
    if extraida.umbral is None or extraida.umbral <= 0:
        faltantes.append("umbral")
    if extraida.tipo is None:
        faltantes.append("tipo")

    if faltantes:
        return None, tuple(faltantes)

    try:
        alerta = Alerta(
            ticker=ticker[:20],
            mercado=(extraida.mercado or "us").strip().lower(),
            tipo=extraida.tipo,
            umbral=_decimal_limpio(extraida.umbral),
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        raise ParserError(f"Gemini devolvió una alerta inválida: {exc}") from exc

    return alerta, ()


def _a_movimientos(
    items: list[_MovimientoItem] | None, hoy: date
) -> tuple[list[Movimiento], tuple[tuple[str, str], ...]]:
    """Separa los ítems completos de los que hay que preguntar.

    Devuelve (movimientos, dudas). Un ítem sin monto usable, o que el modelo
    marcó con `duda`, no se guarda: se cita para preguntar por él solo. Los
    demás siguen su camino, que es todo el punto de esta función.
    """
    completos: list[Movimiento] = []
    dudas: list[tuple[str, str]] = []

    for indice, item in enumerate(items or [], start=1):
        cita = (item.fragmento or item.descripcion or f"ítem {indice}").strip()

        if item.duda:
            dudas.append((cita, item.duda.strip()))
            continue
        if item.monto is None or item.monto <= 0:
            dudas.append((cita, "¿de cuánto fue?"))
            continue
        if item.tipo is None:
            dudas.append((cita, "¿fue un gasto, un ingreso o un ahorro?"))
            continue

        categoria = (item.categoria or "otros").strip().lower()[:60] or "otros"
        descripcion = " ".join((item.descripcion or "").split()).lower()[:60].strip()

        try:
            completos.append(
                Movimiento(
                    fecha=item.fecha or hoy,
                    tipo=item.tipo,
                    monto=_decimal_limpio(item.monto),
                    moneda=item.moneda or Moneda.ARS,
                    categoria=categoria,
                    descripcion=descripcion or categoria,
                    cuenta=(item.cuenta or "").strip()[:40] or None,
                )
            )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            # Un ítem que no valida no tira abajo el mensaje entero: se
            # convierte en una pregunta más.
            logger.info("Ítem inválido en un mensaje múltiple: %s", exc)
            dudas.append((cita, "no me quedó claro, ¿me lo repetís?"))

    return completos, tuple(dudas)


def _a_compra(extraida: _CompraExtraida | None) -> CompraHipotetica | None:
    """La compra hipotética validada, o None si no hay monto con el que trabajar."""
    if extraida is None or extraida.monto is None or extraida.monto <= 0:
        return None

    try:
        return CompraHipotetica(
            monto=_decimal_limpio(extraida.monto),
            moneda=extraida.moneda or Moneda.ARS,
            que=" ".join((extraida.que or "eso").split())[:60] or "eso",
            categoria=(extraida.categoria or "").strip().lower()[:60] or None,
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        logger.info("Compra hipotética inválida: %s", exc)
        return None


def _a_periodo(extraido: _PeriodoExtraido | None, por_defecto: str) -> Periodo:
    if extraido is None:
        return Periodo(etiqueta=por_defecto)
    desde, hasta = extraido.desde, extraido.hasta
    if desde and hasta and desde > hasta:  # el modelo los dio al revés
        desde, hasta = hasta, desde
    etiqueta = (extraido.etiqueta or "").strip().lower() or por_defecto
    return Periodo(desde=desde, hasta=hasta, etiqueta=etiqueta[:40])


def _a_plan(extraido: _PlanExtraido | None) -> PlanConsulta:
    """Convierte lo que devolvió el modelo en un plan validado.

    Todo lo que llega se pasa por Pydantic, que rechaza cualquier valor fuera
    de los enums. Si el modelo inventara una dimensión o una agregación, acá
    se cae y la pregunta se responde con "no entendí", que es infinitamente
    mejor que ejecutar algo que nadie previó.
    """
    if extraido is None:
        return PlanConsulta()

    return PlanConsulta(
        agregacion=extraido.agregacion or Agregacion.TOTAL,
        base_promedio=extraido.base_promedio or BasePromedio.MOVIMIENTO,
        agrupar_por=extraido.agrupar_por or Dimension.NINGUNA,
        tipo=extraido.tipo,
        moneda=extraido.moneda,
        categoria=(extraido.categoria or "").strip().lower()[:60] or None,
        comercio=(extraido.comercio or "").strip().lower()[:60] or None,
        # dict.fromkeys y no set: preserva el orden en que los nombró.
        dias_semana=tuple(dict.fromkeys(extraido.dias_semana or ())),
        periodo=_a_periodo(extraido.periodo, "en total"),
        comparar_con=(
            _a_periodo(extraido.comparar_con, "el período anterior")
            if extraido.comparar_con
            else None
        ),
        # El clamp es del modelo: un limite=500 no puede volverse un mensaje
        # de 500 renglones en Telegram.
        limite=min(max(extraido.limite or 8, 1), 50),
    )


def _a_consulta(extraida: _ConsultaExtraida | None) -> Consulta:
    """Normaliza los filtros de la consulta. Sin filtros = todo el historial."""
    if extraida is None:
        return Consulta()

    etiqueta = (extraida.etiqueta_periodo or "").strip().lower() or "en total"
    categoria = (extraida.categoria or "").strip().lower() or None

    desde, hasta = extraida.desde, extraida.hasta
    if desde and hasta and desde > hasta:  # el modelo los dio al revés
        desde, hasta = hasta, desde

    return Consulta(
        desde=desde,
        hasta=hasta,
        tipo=extraida.tipo,
        moneda=extraida.moneda,
        categoria=categoria,
        etiqueta_periodo=etiqueta,
    )


def interpretar_mensaje(texto: str, hoy: date | None = None) -> Interpretacion:
    """Decide si el mensaje es un registro o una consulta, y extrae sus datos.

    Args:
        texto: el mensaje tal cual lo escribió el usuario.
        hoy: fecha de referencia para las expresiones relativas. Por defecto,
            la fecha actual; se puede fijar para tests reproducibles.

    Raises:
        ParserError: si el texto está vacío, si la API falla o si la respuesta
            no llega a ser utilizable. Siempre con un mensaje legible.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ParserError("El mensaje está vacío, no hay nada que hacer.")

    hoy = hoy or date.today()

    try:
        respuesta = _cliente.models.generate_content(
            model=MODELO,
            contents=texto,
            config=types.GenerateContentConfig(
                system_instruction=_instruccion_sistema(hoy),
                response_mime_type="application/json",
                response_schema=_InterpretacionExtraida,
                temperature=0,  # extracción determinista, no queremos creatividad
                # El modelo razona por defecto; para esta tarea no aporta y
                # agrega latencia y costo en cada mensaje del bot.
                # Los Gemini 3.x usan thinking_level: pasarles el thinking_budget
                # de la generación 2.5 devuelve 400 INVALID_ARGUMENT.
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
    except genai_errors.APIError as exc:
        logger.exception("Falló la llamada a Gemini")
        raise ParserError(
            f"No pude contactar al servicio de interpretación (error {exc.code}). "
            "Probá de nuevo en un momento."
        ) from exc
    except Exception as exc:  # red caída, DNS, timeout, etc.
        logger.exception("Error inesperado llamando a Gemini")
        raise ParserError("No pude contactar al servicio de interpretación.") from exc

    extraida = respuesta.parsed
    if extraida is None:
        # Pasa si el modelo cortó por filtros de seguridad o devolvió JSON roto.
        crudo = (respuesta.text or "").strip()
        logger.warning("Gemini no devolvió un objeto parseable. Crudo: %r", crudo[:500])
        raise ParserError("No entendí el mensaje.")

    if extraida.intencion is Intencion.REGISTRAR:
        if extraida.movimiento is None:
            # Dijo "registrar" pero no mandó los datos: tratamos como no entendido.
            logger.warning("Intención registrar sin movimiento para %r", texto)
            raise ParserError("Dijo registrar pero no extrajo el movimiento.")
        mencion = " ".join((extraida.movimiento.objetivo or "").split()).strip()
        return Interpretacion(
            intencion=Intencion.REGISTRAR,
            movimiento=_a_movimiento(extraida.movimiento),
            # Solo tiene sentido para los ahorros; en el resto se descarta
            # aunque el modelo la haya completado.
            objetivo=mencion or None
            if extraida.movimiento.tipo is TipoMovimiento.AHORRO
            else None,
        )

    if extraida.intencion is Intencion.REGISTRAR_VARIOS:
        movimientos, dudas = _a_movimientos(extraida.movimientos, hoy)
        if not movimientos and not dudas:
            # Dijo "varios" y no mandó ninguno: no hay nada que guardar ni
            # nada que preguntar, así que es lo mismo que no haber entendido.
            logger.warning("Intención registrar_varios sin ítems para %r", texto)
            raise ParserError("Dijo varios movimientos pero no extrajo ninguno.")
        return Interpretacion(
            intencion=Intencion.REGISTRAR_VARIOS,
            movimientos=movimientos,
            dudas=dudas,
        )

    if extraida.intencion is Intencion.REGISTRAR_INVERSION:
        inversion, faltantes = _a_inversion(extraida.inversion, hoy)
        return Interpretacion(
            intencion=Intencion.REGISTRAR_INVERSION,
            inversion=inversion,
            faltantes=faltantes,
        )

    if extraida.intencion is Intencion.CREAR_ALERTA:
        alerta, faltantes = _a_alerta(extraida.alerta)
        return Interpretacion(
            intencion=Intencion.CREAR_ALERTA, alerta=alerta, faltantes=faltantes
        )

    if extraida.intencion is Intencion.VER_ALERTAS:
        return Interpretacion(intencion=Intencion.VER_ALERTAS)

    if extraida.intencion is Intencion.SIMULAR_COMPRA:
        compra = _a_compra(extraida.compra)
        if compra is None:
            # Sin monto no hay nada que analizar. Mejor "no entendí" que un
            # análisis sobre un número inventado.
            logger.info("simular_compra sin monto usable para %r", texto)
            return Interpretacion(intencion=Intencion.DESCONOCIDA)
        return Interpretacion(intencion=Intencion.SIMULAR_COMPRA, compra=compra)

    if extraida.intencion is Intencion.CONSULTA_LIBRE:
        return Interpretacion(
            intencion=Intencion.CONSULTA_LIBRE,
            plan=_a_plan(extraida.plan),
        )

    if extraida.intencion is Intencion.DESCONOCIDA:
        return Interpretacion(intencion=Intencion.DESCONOCIDA)

    return Interpretacion(
        intencion=extraida.intencion,
        consulta=_a_consulta(extraida.consulta),
    )


def parsear_movimiento(texto: str, hoy: date | None = None) -> Movimiento:
    """Interpreta el texto exigiendo que sea un registro.

    Se mantiene por comodidad y para los tests: es `interpretar_mensaje`
    cuando ya sabés que el mensaje es un movimiento.

    Raises:
        ParserError: además de los casos de `interpretar_mensaje`, si el
            mensaje resultó ser una consulta y no un registro.
    """
    resultado = interpretar_mensaje(texto, hoy)
    if resultado.movimiento is None:
        raise ParserError(
            f"El mensaje no es un registro, es {resultado.intencion.value!r}."
        )
    return resultado.movimiento
