// Patrimonio neto mes a mes, en pesos y en dólares.
//
// SOBRE LA PREGUNTA DE CÓMO VALUAR EL HISTÓRICO
//
// Había dos opciones: valuar todo al dólar de hoy, o guardar la cotización de
// cada mes en un snapshot para tener históricos reales de acá en adelante.
// Resultó que no hace falta ninguna de las dos: argentinadatos publica la
// serie del dólar oficial DIARIA desde 2011, gratis y con CORS. Así que cada
// mes se valúa a la cotización que realmente tenía ese mes, incluso para
// meses anteriores a que existiera la app.
//
// Eso es estrictamente mejor que guardar snapshots: no duplica una fuente de
// verdad que ya existe, no puede desincronizarse, y funciona hacia atrás y no
// solo hacia adelante.
//
// La diferencia entre las dos valuaciones no es cosmética. Con el dólar
// pasando de 1.370 a 1.510 en cinco meses, valuar marzo al dólar de hoy diría
// que en marzo tenías menos dólares de los que realmente tenías.
//
// QUÉ ES "PATRIMONIO" ACÁ
// Ahorros acumulados + lo invertido, a costo. No incluye el saldo de la cuenta
// ni los gastos: es lo que se apartó, que es lo que la app sabe. Las
// inversiones van a su precio de compra y no a valor de mercado, porque el
// valor de mercado solo está disponible para algunas y mezclar unas valuadas
// con otras a costo daría una curva que no significa nada.

const URL_SERIE = "https://api.argentinadatos.com/v1/cotizaciones/dolares/oficial";

const CLAVE_CACHE = "cuentix:dolar-historico";
const VIGENCIA_MS = 12 * 60 * 60 * 1000; // la serie crece un punto por día
const TIEMPO_LIMITE_MS = 10000;

/**
 * La serie del dólar oficial, como { "2026-08": 1510, ... } con el ÚLTIMO
 * valor de cada mes.
 *
 * El último y no el promedio: el patrimonio es un stock medido al cierre del
 * mes, así que corresponde el tipo de cambio de ese momento.
 */
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
      // Se pisa: como la serie viene ordenada, queda el último día del mes.
      porMes[fecha.slice(0, 7)] = venta;
    }

    guardarCache(porMes);
    return porMes;
  } catch {
    // Sin serie, la pantalla muestra solo los pesos y lo dice. Preferible a
    // inventar una conversión.
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
    // Sin storage se pide de nuevo. No es grave.
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

/**
 * La serie de patrimonio, mes a mes y acumulada.
 *
 * @param {Array} ahorros movimientos tipo ahorro, TODA la historia
 * @param {Array} inversiones tenencias con precio_compra y fecha_compra
 * @param {string} moneda la moneda en la que están los pesos ("ARS")
 * @param {object|null} serie la del dólar; null = no se pudo traer
 * @returns {{puntos: Array, hayDolar: boolean}}
 */
export function calcular(ahorros, inversiones, moneda, serie) {
  const aportes = new Map(); // mes -> cuánto se sumó ese mes

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

  // Se rellenan los meses sin movimiento: el patrimonio es un stock y sigue
  // existiendo aunque ese mes no se haya ahorrado nada. Sin esto, la línea
  // saltearía meses y daría la impresión de que no había nada.
  const puntos = [];
  let acumulado = 0;
  for (let mes = primero; mes <= ultimo; mes = sumarMes(mes, 1)) {
    acumulado += aportes.get(mes) ?? 0;
    const dolar = serie ? dolarDe(serie, mes) : null;
    puntos.push({
      mes,
      pesos: acumulado,
      dolar,
      // Valuado al dólar DE ESE MES, no al de hoy.
      usd: dolar ? acumulado / dolar : null,
    });
  }

  return { puntos, hayDolar: Boolean(serie) && puntos.some((p) => p.usd !== null) };
}

/**
 * Variación entre el primero y el último punto, en las dos monedas.
 *
 * Las dos pueden ir en direcciones opuestas, y ese contraste es justamente lo
 * que hace útil el indicador: en pesos casi siempre sube, en dólares depende.
 */
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
