// Conversión a dólares para todas las pantallas.
//
// La vista por defecto NO convierte: cada moneda se muestra por separado, que
// es la única forma honesta de mirar los números. Sumar ARS con USD daría un
// total sin significado. La conversión es un modo opcional, explícito, que se
// enciende con el botón "ver todo en USD".
//
// Fuentes (las dos gratuitas, sin API key y con Access-Control-Allow-Origin: *,
// verificado):
//
// - ARS -> USD: dolarapi.com, dólar oficial. Se usa el valor de VENTA porque es
//   el que pagarías para pasar pesos a dólares; con `compra` el total quedaría
//   inflado respecto de lo que realmente podrías comprar.
//
// - EUR -> USD: api.frankfurter.app, que publica las referencias del Banco
//   Central Europeo. Es la paridad internacional real, que es lo que significa
//   "convertir euros a dólares".
//   Si falla, se cae a una paridad derivada de dolarapi: (EUR/ARS) / (USD/ARS).
//   Ese número refleja el euro oficial argentino y no la paridad internacional
//   —hoy dan 1,1392 contra 1,1554, ~1,4% de diferencia—, así que se marca como
//   aproximada y se avisa en la interfaz.
//
// Limitación que no se puede tapar: las cotizaciones son las de HOY. Un gasto
// de marzo convertido con el dólar de hoy no dice cuántos dólares costó
// entonces, dice cuántos vale ahora. Para valuarlo al tipo de cambio del día
// haría falta una serie histórica, que ninguna de estas dos APIs da gratis.

const URL_DOLAR_OFICIAL = "https://dolarapi.com/v1/dolares/oficial";
const URL_EURO_ARS = "https://dolarapi.com/v1/cotizaciones/eur";
const URL_EUR_USD = "https://api.frankfurter.app/latest?from=EUR&to=USD";

// Las cotizaciones se mueven poco dentro de una sesión y la app repinta en cada
// toque de tab. Sin caché, cada repintado dispararía dos fetch.
const CLAVE_CACHE = "cuentix:cotizaciones";
const VIGENCIA_MS = 30 * 60 * 1000; // 30 minutos

const TIEMPO_LIMITE_MS = 8000;

/** Fetch con timeout: sin esto, una API colgada deja la app cargando para siempre. */
async function traer(url) {
  const corte = new AbortController();
  const reloj = setTimeout(() => corte.abort(), TIEMPO_LIMITE_MS);
  try {
    const respuesta = await fetch(url, { signal: corte.signal });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    return await respuesta.json();
  } finally {
    clearTimeout(reloj);
  }
}

function leerCache() {
  try {
    const crudo = sessionStorage.getItem(CLAVE_CACHE);
    if (!crudo) return null;
    const guardado = JSON.parse(crudo);
    if (Date.now() - guardado.momento > VIGENCIA_MS) return null;
    return guardado.cotizaciones;
  } catch {
    return null; // sessionStorage bloqueado o JSON corrupto: se vuelve a pedir
  }
}

function guardarCache(cotizaciones) {
  try {
    sessionStorage.setItem(
      CLAVE_CACHE,
      JSON.stringify({ momento: Date.now(), cotizaciones })
    );
  } catch {
    // Modo privado con storage lleno: seguir sin caché es peor pero funciona.
  }
}

/**
 * Cuántos USD vale una unidad de cada moneda.
 *
 * @returns {Promise<{tasas: {ARS: number, USD: number, EUR: number},
 *                    actualizado: string|null, eurAproximado: boolean}>}
 */
export async function traerCotizaciones() {
  const enCache = leerCache();
  if (enCache) return enCache;

  // Las dos en paralelo: son independientes y así se paga la latencia una vez.
  const [oficial, eurUsd] = await Promise.allSettled([
    traer(URL_DOLAR_OFICIAL),
    traer(URL_EUR_USD),
  ]);

  if (oficial.status !== "fulfilled" || !Number(oficial.value?.venta)) {
    throw new Error("No pude traer la cotización del dólar oficial.");
  }
  const arsPorUsd = Number(oficial.value.venta);

  let usdPorEur = null;
  let eurAproximado = false;

  if (eurUsd.status === "fulfilled" && Number(eurUsd.value?.rates?.USD)) {
    usdPorEur = Number(eurUsd.value.rates.USD);
  } else {
    // Plan B: paridad cruzada contra el peso, con los dos valores de dolarapi.
    try {
      const euroArs = await traer(URL_EURO_ARS);
      if (Number(euroArs?.venta)) {
        usdPorEur = Number(euroArs.venta) / arsPorUsd;
        eurAproximado = true;
      }
    } catch {
      // Se resuelve abajo dejando usdPorEur en null.
    }
  }

  const cotizaciones = {
    tasas: {
      USD: 1,
      ARS: 1 / arsPorUsd,
      // null = no se pudo cotizar; convertir() deja esos montos sin tocar.
      EUR: usdPorEur,
    },
    arsPorUsd,
    usdPorEur,
    eurAproximado,
    actualizado: oficial.value.fechaActualizacion ?? null,
  };

  guardarCache(cotizaciones);
  return cotizaciones;
}

/** true si `moneda` se puede pasar a USD con estas cotizaciones. */
export function sePuedeConvertir(moneda, cotizaciones) {
  return Number.isFinite(cotizaciones?.tasas?.[moneda]);
}

/**
 * Devuelve los movimientos expresados en USD.
 *
 * Los que no se pueden convertir (una moneda sin cotización) se devuelven tal
 * cual, con su moneda original: se prefiere mostrarlos aparte y bien antes que
 * omitirlos de un total que el usuario cree completo.
 *
 * Como el resultado sigue siendo una lista de movimientos con `monto` y
 * `moneda`, todo lo que ya existe —porMoneda, totalPorTipo, la dona, las
 * pantallas— funciona sin enterarse de que hubo una conversión.
 */
export function convertirMovimientos(movimientos, cotizaciones) {
  return movimientos.map((m) => {
    if (m.moneda === "USD") return m;
    const tasa = cotizaciones?.tasas?.[m.moneda];
    if (!Number.isFinite(tasa)) return m;

    return {
      ...m,
      // Redondeo a centavo: sin esto quedan colas de float que después se
      // arrastran a todas las sumas.
      monto: Math.round(Number(m.monto) * tasa * 100) / 100,
      moneda: "USD",
      // Rastro para poder mostrar el original si alguna pantalla lo necesita.
      monedaOriginal: m.moneda,
      montoOriginal: Number(m.monto),
    };
  });
}

/** Monedas de la lista que quedaron sin convertir. */
export function monedasSinConvertir(movimientos, cotizaciones) {
  return [
    ...new Set(
      movimientos
        .filter((m) => m.moneda !== "USD" && !sePuedeConvertir(m.moneda, cotizaciones))
        .map((m) => m.moneda)
    ),
  ].sort();
}

/** "1 USD = $1.520" para mostrar de dónde salieron los números. */
export function resumenDeTasas(cotizaciones) {
  const partes = [`1 USD = ${cotizaciones.arsPorUsd.toLocaleString("es-AR")} ARS`];
  if (Number.isFinite(cotizaciones.usdPorEur)) {
    const eur = cotizaciones.usdPorEur.toLocaleString("es-AR", {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });
    partes.push(`1 EUR = ${eur} USD${cotizaciones.eurAproximado ? " (aprox.)" : ""}`);
  }
  return partes.join(" · ");
}
