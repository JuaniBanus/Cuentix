"""Rendimientos de billeteras virtuales: de dónde salen las tasas.

=========================== QUÉ FUENTE SE ELIGIÓ ===========================

api.argentinadatos.com, que es una API pública, gratuita, sin clave y con CORS
abierto. NO es un scraper de HTML.

Se eligió después de descartar la alternativa obvia: comparatasas.ar, que es el
comparador más conocido, no expone ninguna API (api.comparatasas.ar ni siquiera
resuelve por DNS). Leer sus tasas obligaba a parsear el HTML de una app Nuxt,
que es exactamente el tipo de acoplamiento frágil que se quería evitar.

Mirando de dónde saca comparatasas sus propios assets aparece la respuesta:
carga los logos desde api.argentinadatos.com. Es del mismo autor y usa la misma
API que usamos nosotros. O sea que vamos a la fuente en vez de al intermediario.

Y no es una dependencia nueva: app/tasas.py ya usa esta misma API para el plazo
fijo desde antes. Si se cae, ya teníamos un problema.

Se usan dos endpoints, por dos clases de producto distintas:

1. FONDOS (/v1/finanzas/fci/fondos) — la mayoría de las billeteras no pagan una
   tasa: invierten el saldo en un fondo común de dinero. Mercado Pago es
   "Mercado Fondo - Clase A", Ualá es "Ualintec Ahorro Pesos - Clase A". El
   endpoint publica datos de la CAFCI, incluido `rendimientos.unMes`, que es el
   rendimiento del último mes. Es la misma metodología que declara comparatasas
   ("los fondos comunes vinculados a billeteras se calculan a partir del
   rendimiento del último mes según los datos de la CAFCI").

2. ENTIDADES (/v1/finanzas/rendimientos) — las que declaran una tasa propia en
   pesos. Acá el número lo informa la entidad, no se deriva de nada, y de yapa
   trae el tope de monto hasta el que se paga (`bonusThreshold`).

========================= QUÉ TAN FRÁGIL ES ESTO =========================

Con honestidad, porque la pregunta es justa. Hay tres piezas y NO son igual de
sólidas:

- La API en sí: sólida. Es JSON versionado (/v1/), sin clave, y ya la usábamos.
  Si cambia el formato, se rompe el parseo y no se actualiza nada más.

- El endpoint de entidades: sólido, se lee tal cual viene. Si mañana agregan una
  billetera nueva en pesos, aparece sola sin tocar código.

- EL MAPEO billetera -> fondo (CATALOGO_FCI): esta es la parte frágil, y no hay
  forma de que no lo sea. Ningún organismo publica "Mercado Pago usa Mercado
  Fondo": es una relación comercial que se sabe mirando la app. Está escrita a
  mano acá.

  Cómo falla, en concreto: si una billetera cambia de fondo, vamos a mostrarle
  al usuario la TNA del fondo VIEJO, que es un número plausible y equivocado —la
  peor clase de error para una tasa—. Si en cambio el fondo se renombra o deja
  de publicarse, esa billetera simplemente desaparece de la lista, que es el
  modo de fallar bueno.

  No hay defensa automática contra lo primero. Lo que sí hay: cada fila guarda
  en `fondo` de qué fondo salió, así que el número siempre es auditable contra
  la CAFCI sin tener que leer este archivo.

========================== CÓMO SE AÍSLA EL DAÑO ==========================

El pedido era que si esto se rompe no se lleve puesto al resto. Cuatro reglas,
y las cuatro están implementadas abajo:

1. `actualizar()` NUNCA levanta una excepción. Devuelve un resumen con `ok`
   en False y el motivo. Quien la llama no necesita un try.

2. Nada se borra jamás. Si la fuente no responde, las filas viejas quedan como
   estaban, con SU fecha —que es vieja y la pantalla lo va a mostrar—. Preferimos
   una tasa de la semana pasada, fechada, antes que una pantalla en blanco.

3. Cada billetera se procesa por separado. Una que falle no arrastra a las
   demás: se cuenta como descartada y la corrida sigue.

4. Los valores absurdos se descartan antes de guardarse (ver TNA_MAXIMA). Si la
   fuente algún día cambia de porcentaje a fracción, un 0,15 se guardaría como
   0,15% en vez de 15%; el rango no atrapa ese caso, pero sí atrapa el inverso,
   que es el que produce números escandalosos en pantalla.

============================ EL DETALLE DE LA TNA ============================

`unMes` viene en porcentaje y es el rendimiento de un mes: 1.4774 es 1,4774%.
La TNA se calcula como `unMes * 12`, y no como `unMes * 365 / 30`.

Por qué 12 y no 12,1667: para que el ida y vuelta cierre exacto. La web muestra
la ganancia mensual como TNA/12 —el mismo criterio que app/tasas.py, donde la
TNA es nominal con capitalización a 30 días—, así que multiplicar por 12 acá
hace que dividir por 12 allá devuelva el rendimiento mensual original. Con
365/30 el número que ve el usuario no sería el que publicó la CAFCI.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

URL_FONDOS = "https://api.argentinadatos.com/v1/finanzas/fci/fondos"
URL_ENTIDADES = "https://api.argentinadatos.com/v1/finanzas/rendimientos"

# El de fondos son ~33 MB de JSON (1,6 MB comprimidos). El límite es generoso
# porque el cron corre una vez por día y no hay nadie esperando en pantalla.
TIEMPO_LIMITE = 90.0

# Tasas por encima de esto son un error de unidades, no una oportunidad.
TNA_MAXIMA = Decimal("300")
# Un mes que rindió más que esto tampoco es real.
UN_MES_MAXIMO = Decimal("50")

# --------------------------------------------------------------------------
# El catálogo: qué fondo hay atrás de cada billetera
# --------------------------------------------------------------------------
#
# (nombre que ve el usuario, nombre exacto del fondo en la CAFCI, tope de monto)
#
# El nombre del fondo tiene que coincidir CARÁCTER POR CARÁCTER con el campo
# `nombre` de la API, clase incluida. Se compara exacto y no por parecido a
# propósito: "Delta Pesos - Clase A" y "Delta Pesos - Clase X" son dos billeteras
# distintas (Fiwind y Personal Pay) con tasas distintas, y un match aproximado
# las confundiría.
#
# El tope es None en todos: un fondo común no tiene tope de monto. Se deja la
# columna igual porque las cuentas remuneradas sí lo tienen.
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

# Cómo se llama en pantalla cada entidad del endpoint de entidades. La clave es
# el campo `entidad` de la API, en minúsculas.
#
# Es solo cosmético: una entidad que no esté acá igual se muestra, con el nombre
# capitalizado. Eso es lo que hace que una billetera nueva aparezca sola.
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
    # NaN e infinito pasan el Decimal() pero rompen cualquier comparación.
    return numero if numero.is_finite() else None


def _fecha(valor: object) -> date | None:
    """'2026-08-14' -> date. None si no se puede leer."""
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Fuente 1: fondos comunes de dinero
# --------------------------------------------------------------------------


def _leer_fondos(nombres: set[str]) -> dict[str, dict]:
    """Los fondos pedidos, leyendo la respuesta DE A UN OBJETO POR VEZ.

    Por qué en streaming y no con un `response.json()`:

    El endpoint devuelve 33 MB porque trae la composición de cartera completa de
    4.800 fondos, y nosotros queremos 26 sin la cartera. Un json.loads de eso
    arma el árbol entero en memoria —del orden de 250 MB de objetos Python— y el
    plan gratuito de Render tiene 512 MB para todo el bot. Sería un OOM en la
    corrida del cron que se llevaría puesto al proceso que atiende Telegram.

    Leyendo incremental y descartando lo que no interesa, el pico medido es de
    9,4 MB y tarda unos 7 segundos. Ese es el motivo de todo el enroque de abajo:
    no es prematuro, es la diferencia entre andar y tirar el proceso.

    Se hace a mano con raw_decode y no con ijson para no sumar una dependencia
    por una función.
    """
    decodificador = json.JSONDecoder()
    encontrados: dict[str, dict] = {}
    buffer = ""
    arrancado = False

    with httpx.stream("GET", URL_FONDOS, timeout=TIEMPO_LIMITE) as respuesta:
        respuesta.raise_for_status()

        for pedazo in respuesta.iter_text(65536):
            buffer += pedazo

            # El JSON es {"fechaActualizacion": ..., "fondos": [ ... ]}: hay que
            # saltear la cabecera y pararse justo después del corchete.
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
                    # Todavía no llegó el objeto entero: se espera al próximo
                    # pedazo. Este es el caso normal, no un error.
                    buffer = resto
                    break

                buffer = resto[fin:]
                nombre = objeto.get("nombre")
                if nombre in nombres:
                    encontrados[nombre] = objeto
                # El resto se descarta acá mismo: es lo que mantiene el pico bajo.

            # Cortar apenas estén todos evitaría bajar los 33 MB completos, pero
            # los fondos no vienen ordenados y el que falta puede ser el último.

    # Si nunca se encontró el array, lo que llegó no era la respuesta esperada:
    # una página de error de Cloudflare, un redirect a un login, un HTML. Sin
    # este control el parseo devolvería {} y el resto del módulo lo leería como
    # "hoy ningún fondo del catálogo tenía datos", que es un fallo SILENCIOSO:
    # se reportaría ok y nos habríamos quedado sin las 26 billeteras.
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
            # El fondo cambió de nombre o dejó de publicarse. La billetera queda
            # afuera de esta corrida; su fila anterior sigue en la base con su
            # fecha vieja, que es justo lo que queremos que pase.
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

    # Que se caiga UNA billetera del catálogo es normal y se tolera: cambió el
    # nombre de un fondo y hay que actualizar la constante. Que se caigan TODAS
    # no es eso: es que la API cambió cómo nombra los fondos, o que empezó a
    # devolver otra cosa. Se reporta como falla en vez de guardar cero filas en
    # silencio, que es como un scraper roto pasa desapercibido durante meses.
    if not filas:
        raise RendimientosError(
            "ningún fondo del catálogo apareció en la respuesta "
            "(¿cambiaron los nombres en la CAFCI?)"
        )

    if sin_datos:
        logger.warning("Sin datos de fondo para: %s", ", ".join(sin_datos))

    return filas


# --------------------------------------------------------------------------
# Fuente 2: cuentas remuneradas declaradas por la entidad
# --------------------------------------------------------------------------


def _filas_de_entidades() -> list[dict]:
    """Las entidades que declaran una tasa en PESOS.

    El endpoint trae sobre todo cripto (USDT, BTC): se filtra por moneda ARS,
    que es lo único comparable con una billetera en pesos.
    """
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

            # `bonusThreshold` es el saldo hasta el que se paga la tasa. Es el
            # único lugar de todo esto donde el tope viene del proveedor en vez
            # de estar escrito a mano.
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
            break  # una fila por entidad: la primera en pesos

    # Cero acá no se trata como falla, al revés que en los fondos: este endpoint
    # es mayormente cripto y que ninguna entidad declare una tasa en pesos es un
    # resultado posible, no un síntoma. Se deja anotado para poder mirarlo.
    if not filas:
        logger.info("Ninguna entidad declara rendimiento en pesos")

    return filas


# --------------------------------------------------------------------------
# Lo que llama el cron
# --------------------------------------------------------------------------


def actualizar() -> dict:
    """Trae las tasas de las dos fuentes y las guarda. NUNCA levanta.

    Devuelve un resumen para que el cron lo pueda loguear y para poder mirar
    desde afuera si esto sigue vivo, sin entrar al servidor.

    Las dos fuentes se intentan por separado y de forma independiente: que se
    caiga la de fondos no tiene por qué dejarnos también sin las cuentas
    remuneradas, que salen de otro endpoint.
    """
    # El import va acá adentro y no arriba a propósito. db importa el cliente de
    # Supabase y la config; si algo de eso fallara, un import arriba rompería el
    # módulo entero al cargarse, y este archivo lo importa main.py al arrancar.
    # Adentro de la función, el peor caso es que falle esta corrida.
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
        # No se guarda nada y no se borra nada: quedan las tasas anteriores con
        # su fecha vieja, que la pantalla va a mostrar como vieja.
        logger.error("Ninguna fuente respondió; se conservan las tasas anteriores")
        return {"ok": False, "guardadas": 0, "problemas": problemas or ["sin datos"]}

    # Dos billeteras pueden compartir fondo (Claro Pay y CencoPay), pero dos
    # filas con el mismo NOMBRE romperían el upsert por la unique de la columna.
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
