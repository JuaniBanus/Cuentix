"""Respuestas fijas a saludos y comandos, resueltas sin pasar por Gemini.

Un "hola" no tiene nada que interpretar: mandarlo al modelo sería pagar una
llamada, y esperar un segundo, para que conteste que no entendió. Acá se
resuelve con texto fijo antes de que el mensaje llegue al parser.
"""

from __future__ import annotations

import unicodedata

MSG_BIENVENIDA = """\
¡Hola! Soy Cuentix 🧮, tu asistente para llevar las cuentas.

Escribime como le hablarías a un amigo y yo anoto:
• «gasté 8 lucas en el súper»
• «me entraron 300 mil de sueldo»
• «puse 500 dólares en cripto»
• «aparté 50 mil para el viaje»

Y cuando quieras saber cómo venís, preguntame:
• «¿cuánto gasté este mes?»
• «¿en qué se me va la plata?»
• «¿cómo vengo este mes?»

Entiendo fechas («ayer», «el lunes», «el 3») y la jerga de siempre:
lucas, palos y gambas.

Escribí /ayuda para ver todo lo que puedo hacer."""

MSG_AYUDA = """\
🧮 Cuentix — todo lo que puedo hacer

📝 ANOTAR MOVIMIENTOS
Escribime en lenguaje natural y yo me doy cuenta de qué se trata.

• Gastos — plata que sale y no vuelve
  «gasté 8 lucas en el súper» · «pagué 45 mil de luz»
• Ingresos — plata que entra
  «cobré el sueldo, 900 mil» · «me entraron 200 mil de un freelance»
• Ahorros — plata que guardás y sigue siendo tuya
  «aparté 50 mil para el viaje» · «puse 100 mil en el plazo fijo»
• Inversiones — plata que ponés a rendir, asumiendo riesgo
  «compré 500 dólares» · «metí 80 mil en cripto»

Si dudás entre ahorro e inversión: si puede perder valor, es inversión.

🎯 OBJETIVOS DE AHORRO
Si me decís para qué apartás la plata, la imputo al objetivo y te digo cómo
venís: «guardé 150 mil para el viaje a Europa».
Si no tengo uno que coincida, te pregunto antes de crearlo. Nunca lo adivino.

🏦 DÓNDE GUARDÁS LA PLATA
Si me decís dónde queda, lo anoto: «guardé 50 mil en el banco»,
«aparté efectivo», «lo puse en Mercado Pago». Si no lo aclarás, no pasa
nada: lo dejo en blanco y no invento.

📊 PREGUNTARME
• Totales — «¿cuánto gasté este mes?» · «¿cuánto llevo ahorrado en dólares?»
• Por rubro — «¿en qué se me va la plata?» · «¿cuánto gasté en supermercado?»
• Balance — «¿cómo vengo este mes?» · «balance de julio»

🗓 FECHAS
Entiendo «ayer», «anteayer», «el lunes», «el 3», «la semana pasada».
Si no aclarás nada, uso el día de hoy.

💵 MONTOS
Jerga: luca = 1.000 · palo = 1.000.000 · gamba = 100.
Formato argentino: «15.340,50».
Si no aclarás moneda, asumo pesos. Para dólares: «dólares», «usd», «verdes».

🌙 CIERRE DEL DÍA
Contame todo junto y lo separo solo:
«gasté 5 lucas en el súper, 2 en un café y cargué 30 de nafta»
→ registro los tres por separado y te confirmo el total.
Si algún ítem me deja dudando, pregunto SOLO por ese y el resto queda anotado.

Y si querés, te escribo yo: /recordatorio 21 y todas las noches a esa hora
te pregunto cómo te fue.

💰 DÓNDE RINDE MÁS LA PLATA
/rendimientos — el ranking de billeteras virtuales por TNA, con cuánto
paga cada una por mes y desde cuándo es el dato.
Las tasas se actualizan solas una vez por día.

⚙️ COMANDOS
/start — presentación
/ayuda — esta ayuda
/rendimientos — comparar billeteras virtuales
/recordatorio — ver si tenés recordatorio diario
/recordatorio 21 — que te escriba a esa hora
/recordatorio off — apagarlo

Todavía no puedo editar ni borrar movimientos ya cargados."""

# Las claves van normalizadas: minúsculas, sin tildes y sin signos.
_SALUDOS = frozenset(
    {
        "/start",
        "hola",
        "holaa",
        "holaaa",
        "holis",
        "ola",
        "buenas",
        "buen dia",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "que tal",
        "que onda",
        "como andas",
        "como va",
        "hola cuentix",
        "buenas cuentix",
    }
)

_AYUDA = frozenset(
    {
        "/ayuda",
        "/help",
        "ayuda",
        "help",
        "que podes hacer",
        "que sabes hacer",
        "que puedo hacer",
        "que haces",
        "como funciona",
        "como te uso",
        "para que servis",
        "comandos",
    }
)

# Los signos no aportan nada para comparar: "¿qué podés hacer?" tiene que
# entrar por la misma puerta que "que podes hacer".
_SIGNOS = " ¡!¿?.,;:…\"'"


def _normalizar(texto: str) -> str:
    """Baja a minúsculas, saca tildes y signos, y colapsa los espacios."""
    # NFD separa cada letra de su tilde, y "Mn" (marca no espaciada) es
    # justamente esa tilde suelta: descartándola queda la letra pelada.
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(caracter) != "Mn"
    )
    return " ".join(sin_tildes.strip(_SIGNOS).split())


def respuesta_directa(texto: str) -> str | None:
    """La respuesta fija que corresponde al mensaje, o None si no hay ninguna.

    None significa "esto hay que interpretarlo": el mensaje sigue camino al
    parser como siempre.

    Compara el mensaje ENTERO y no su comienzo, a propósito. Con un `startswith`
    un "hola, gasté 8 lucas en el súper" se comería el gasto y contestaría el
    saludo. Así, un saludo con algo más atrás es un mensaje común y se
    interpreta normal.
    """
    clave = _normalizar(texto)

    # En un grupo, Telegram manda "/start@Cuentia_Bot" en lugar de "/start".
    if clave.startswith("/"):
        clave = clave.split("@", 1)[0]

    if clave in _SALUDOS:
        return MSG_BIENVENIDA
    if clave in _AYUDA:
        return MSG_AYUDA
    return None
