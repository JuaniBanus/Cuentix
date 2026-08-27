// Cotizaciones del dólar: las de hoy y la serie histórica.

const URL_HOY = "https://dolarapi.com/v1/dolares";
const URL_SERIE = "https://api.argentinadatos.com/v1/cotizaciones/dolares";

const CLAVE_HOY = "cuentix:dolar-hoy";
const CLAVE_SERIE = "cuentix:dolar-serie";
const VIGENCIA_HOY = 10 * 60 * 1000;
const VIGENCIA_SERIE = 6 * 60 * 60 * 1000;
const TIEMPO_LIMITE = 10000;

export const CASAS = [
  { id: "oficial", nombre: "Oficial" },
  { id: "blue", nombre: "Blue" },
  { id: "bolsa", nombre: "MEP" },
  { id: "contadoconliqui", nombre: "CCL" },
  { id: "cripto", nombre: "Cripto" },
  { id: "tarjeta", nombre: "Tarjeta" },
  { id: "mayorista", nombre: "Mayorista" },
];

const NOMBRE = new Map(CASAS.map((c) => [c.id, c.nombre]));
export const nombreDe = (id) => NOMBRE.get(id) ?? id;

async function traer(url, señal) {
  const respuesta = await fetch(url, { signal: señal });
  if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
  return respuesta.json();
}

function leerCache(clave, vigencia) {
  try {
    const crudo = sessionStorage.getItem(clave);
    if (!crudo) return null;
    const g = JSON.parse(crudo);
    return Date.now() - g.momento > vigencia ? null : g.dato;
  } catch {
    return null;
  }
}

function guardarCache(clave, dato) {
  try {
    sessionStorage.setItem(clave, JSON.stringify({ momento: Date.now(), dato }));
  } catch {
  }
}

async function conTimeout(url, clave, vigencia) {
  const enCache = leerCache(clave, vigencia);
  if (enCache) return enCache;

  const corte = new AbortController();
  const reloj = setTimeout(() => corte.abort(), TIEMPO_LIMITE);
  try {
    const dato = await traer(url, corte.signal);
    guardarCache(clave, dato);
    return dato;
  } finally {
    clearTimeout(reloj);
  }
}

/** Todo lo que el panel necesita. */
export async function traerDolar() {
  const [hoy, historia] = await Promise.allSettled([
    conTimeout(URL_HOY, CLAVE_HOY, VIGENCIA_HOY),
    conTimeout(URL_SERIE, CLAVE_SERIE, VIGENCIA_SERIE),
  ]);

  if (hoy.status !== "fulfilled" || !Array.isArray(hoy.value)) {
    return {
      cotizaciones: [],
      serie: {},
      error: "No pude traer las cotizaciones del dólar. Probá en un rato.",
    };
  }

  const serie = {};
  if (historia.status === "fulfilled" && Array.isArray(historia.value)) {
    for (const punto of historia.value) {
      const venta = Number(punto?.venta);
      if (!punto?.casa || !punto?.fecha || !Number.isFinite(venta)) continue;
      (serie[punto.casa] ??= []).push({ fecha: punto.fecha, venta });
    }
    for (const casa of Object.keys(serie)) {
      serie[casa].sort((a, b) => a.fecha.localeCompare(b.fecha));
    }
  }

  const cotizaciones = CASAS
    .map(({ id }) => {
      const c = hoy.value.find((x) => x.casa === id);
      if (!c) return null;

      const venta = Number(c.venta);
      const compra = Number(c.compra);
      const puntos = serie[id] ?? [];
      const previo = puntos.length >= 2 ? puntos[puntos.length - 2].venta : null;

      return {
        casa: id,
        nombre: nombreDe(id),
        compra: Number.isFinite(compra) ? compra : null,
        venta: Number.isFinite(venta) ? venta : null,
        previo,
        variacion: previo && venta ? venta / previo - 1 : null,
        actualizado: c.fechaActualizacion ?? null,
      };
    })
    .filter(Boolean);

  return {
    cotizaciones,
    serie,
    error:
      historia.status !== "fulfilled"
        ? "Traje las cotizaciones de hoy, pero no el histórico: no puedo mostrar el gráfico ni la variación."
        : null,
  };
}

/** La brecha entre dos casas, en porcentaje sobre la más barata. */
export function brecha(cotizaciones, a, b) {
  const uno = cotizaciones.find((c) => c.casa === a)?.venta;
  const otro = cotizaciones.find((c) => c.casa === b)?.venta;
  if (!uno || !otro) return null;
  return { valor: otro / uno - 1, base: uno, contra: otro };
}

/** El análisis del día: qué se movió más y para dónde. */
export function analisis(cotizaciones) {
  const conVariacion = cotizaciones.filter((c) => c.variacion !== null);
  if (!conVariacion.length) return null;

  const ordenadas = [...conVariacion].sort((a, b) => b.variacion - a.variacion);
  const subieron = conVariacion.filter((c) => c.variacion > 0.0005).length;
  const bajaron = conVariacion.filter((c) => c.variacion < -0.0005).length;

  return {
    masSubio: ordenadas[0].variacion > 0.0005 ? ordenadas[0] : null,
    masBajo: ordenadas.at(-1).variacion < -0.0005 ? ordenadas.at(-1) : null,
    subieron,
    bajaron,
    quietas: conVariacion.length - subieron - bajaron,
    brechaBlue: brecha(cotizaciones, "oficial", "blue"),
    brechaMep: brecha(cotizaciones, "oficial", "bolsa"),
  };
}

/** Los últimos N días de una casa, para el gráfico. */
export function ultimos(serie, casa, dias = 45) {
  return (serie[casa] ?? []).slice(-dias);
}
