// Patrimonio neto mes a mes, en pesos y en dólares.

const URL_SERIE = "https://api.argentinadatos.com/v1/cotizaciones/dolares/oficial";

const CLAVE_CACHE = "cuentix:dolar-historico";
const VIGENCIA_MS = 12 * 60 * 60 * 1000;
const TIEMPO_LIMITE_MS = 10000;

/** La serie del dólar oficial, como { "2026-08": 1510, ... } con el ÚLTIMO */
export async function serieDolar() {
  const enCache = leerCache();
  if (enCache) return enCache;

  const corte = new AbortController();
  const reloj = setTimeout(() => corte.abort(), TIEMPO_LIMITE_MS);
  try {
    const respuesta = await fetch(URL_SERIE, { signal: corte.signal });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    const datos = await respuesta.json();

    const porMes = {};
    for (const punto of datos) {
      const fecha = punto?.fecha;
      const venta = Number(punto?.venta);
      if (!fecha || !Number.isFinite(venta) || venta <= 0) continue;
      porMes[fecha.slice(0, 7)] = venta;
    }

    guardarCache(porMes);
    return porMes;
  } catch {
    return null;
  } finally {
    clearTimeout(reloj);
  }
}

function leerCache() {
  try {
    const crudo = sessionStorage.getItem(CLAVE_CACHE);
    if (!crudo) return null;
    const guardado = JSON.parse(crudo);
    return Date.now() - guardado.momento > VIGENCIA_MS ? null : guardado.serie;
  } catch {
    return null;
  }
}

function guardarCache(serie) {
  try {
    sessionStorage.setItem(CLAVE_CACHE, JSON.stringify({ momento: Date.now(), serie }));
  } catch {
  }
}

/** El dólar de ese mes, o el del mes anterior más cercano si falta. */
function dolarDe(serie, mes) {
  if (serie[mes]) return serie[mes];
  const meses = Object.keys(serie).sort();
  let ultimo = null;
  for (const m of meses) {
    if (m > mes) break;
    ultimo = serie[m];
  }
  return ultimo;
}

function mesDe(iso) {
  return String(iso ?? "").slice(0, 7);
}

function sumarMes(mes, cuantos) {
  const [a, m] = mes.split("-").map(Number);
  const d = new Date(a, m - 1 + cuantos, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** La serie de patrimonio, mes a mes y acumulada. */
export function calcular(ahorros, inversiones, moneda, serie) {
  const aportes = new Map();

  for (const m of ahorros ?? []) {
    if (m.moneda !== moneda || m.tipo !== "ahorro") continue;
    const mes = mesDe(m.fecha);
    if (!mes) continue;
    aportes.set(mes, (aportes.get(mes) ?? 0) + (Number(m.monto) || 0));
  }

  for (const i of inversiones ?? []) {
    if (i.moneda !== moneda) continue;
    const mes = mesDe(i.fecha_compra);
    if (!mes) continue;
    const costo = (Number(i.cantidad) || 0) * (Number(i.precio_compra) || 0);
    if (costo > 0) aportes.set(mes, (aportes.get(mes) ?? 0) + costo);
  }

  if (!aportes.size) return { puntos: [], hayDolar: Boolean(serie) };

  const meses = [...aportes.keys()].sort();
  const primero = meses[0];
  const ultimo = meses[meses.length - 1];

  const puntos = [];
  let acumulado = 0;
  for (let mes = primero; mes <= ultimo; mes = sumarMes(mes, 1)) {
    acumulado += aportes.get(mes) ?? 0;
    const dolar = serie ? dolarDe(serie, mes) : null;
    puntos.push({
      mes,
      pesos: acumulado,
      dolar,
      usd: dolar ? acumulado / dolar : null,
    });
  }

  return { puntos, hayDolar: Boolean(serie) && puntos.some((p) => p.usd !== null) };
}

/** Variación entre el primero y el último punto, en las dos monedas. */
export function variacion(puntos) {
  const utiles = (puntos ?? []).filter((p) => p.pesos > 0);
  if (utiles.length < 2) return null;

  const primero = utiles[0];
  const ultimo = utiles[utiles.length - 1];

  const enPesos = ultimo.pesos / primero.pesos - 1;
  const enDolares =
    primero.usd && ultimo.usd ? ultimo.usd / primero.usd - 1 : null;

  return {
    desde: primero.mes,
    hasta: ultimo.mes,
    pesosInicial: primero.pesos,
    pesosFinal: ultimo.pesos,
    usdInicial: primero.usd,
    usdFinal: ultimo.usd,
    enPesos,
    enDolares,
  };
}
