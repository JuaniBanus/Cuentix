// Conversión a dólares para todas las pantallas.

const URL_DOLAR_OFICIAL = "https://dolarapi.com/v1/dolares/oficial";
const URL_EURO_ARS = "https://dolarapi.com/v1/cotizaciones/eur";
const URL_EUR_USD = "https://api.frankfurter.app/latest?from=EUR&to=USD";

const CLAVE_CACHE = "cuentix:cotizaciones";
const VIGENCIA_MS = 30 * 60 * 1000;

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
    return null;
  }
}

function guardarCache(cotizaciones) {
  try {
    sessionStorage.setItem(
      CLAVE_CACHE,
      JSON.stringify({ momento: Date.now(), cotizaciones })
    );
  } catch {
  }
}

/** Cuántos USD vale una unidad de cada moneda. */
export async function traerCotizaciones() {
  const enCache = leerCache();
  if (enCache) return enCache;

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
    try {
      const euroArs = await traer(URL_EURO_ARS);
      if (Number(euroArs?.venta)) {
        usdPorEur = Number(euroArs.venta) / arsPorUsd;
        eurAproximado = true;
      }
    } catch {
    }
  }

  const cotizaciones = {
    tasas: {
      USD: 1,
      ARS: 1 / arsPorUsd,
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

/** Devuelve los movimientos expresados en USD. */
export function convertirMovimientos(movimientos, cotizaciones) {
  return movimientos.map((m) => {
    if (m.moneda === "USD") return m;
    const tasa = cotizaciones?.tasas?.[m.moneda];
    if (!Number.isFinite(tasa)) return m;

    return {
      ...m,
      monto: Math.round(Number(m.monto) * tasa * 100) / 100,
      moneda: "USD",
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
