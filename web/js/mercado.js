// Precios de mercado para acciones, ETFs, CEDEARs y bonos.

import { BACKEND_URL } from "./config.js";
import { sesionActual } from "./data.js";

const CLAVE_CACHE = "cuentix:precios-mercado";

const FRESCO_MS = 60 * 60 * 1000;

const ESPERA_MS = 90_000;

/** Qué mercado le corresponde a una tenencia, por su moneda. */
export function mercadoDe(inversion) {
  return inversion?.moneda === "ARS" ? "ar" : "us";
}

/** Los tipos que se valúan por el proxy. La cripto va por CoinGecko. */
export function vaPorElProxy(tipo) {
  return ["accion", "etf", "cedear", "bono", "fci"].includes(tipo);
}


function leerGuardados() {
  try {
    return JSON.parse(localStorage.getItem(CLAVE_CACHE)) || {};
  } catch {
    return {};
  }
}

function guardar(clave, precio, moneda) {
  try {
    const todos = leerGuardados();
    todos[clave] = { precio, moneda, cuando: Date.now() };
    localStorage.setItem(CLAVE_CACHE, JSON.stringify(todos));
  } catch {
  }
}

/** El último precio que supimos de este activo, si alguna vez lo supimos. */
export function ultimoConocido(ticker, mercado) {
  const guardado = leerGuardados()[`${mercado}:${String(ticker).toUpperCase()}`];
  if (!guardado || !Number.isFinite(guardado.precio)) return null;
  return { ...guardado, fresco: Date.now() - guardado.cuando < FRESCO_MS };
}


async function pedir(ruta) {
  if (!BACKEND_URL) throw new Error("Falta configurar BACKEND_URL en config.js.");

  const sesion = await sesionActual();
  if (!sesion?.access_token) {
    const error = new Error("Tu sesión venció. Entrá de nuevo para ver precios.");
    error.sinSesion = true;
    throw error;
  }

  const respuesta = await fetch(`${BACKEND_URL}${ruta}`, {
    headers: { Authorization: `Bearer ${sesion.access_token}` },
    signal: AbortSignal.timeout(ESPERA_MS),
  });

  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null);
    const error = new Error(cuerpo?.detail || `El proveedor respondió ${respuesta.status}`);
    error.sinCobertura = respuesta.status === 400 || respuesta.status === 502;
    error.sinConfigurar = respuesta.status === 503;
    error.sinSesion = respuesta.status === 401;
    if (respuesta.status === 429) {
      error.demasiadosPedidos = true;
      error.esperaSegundos = Number(respuesta.headers.get("retry-after")) || 60;
    }
    throw error;
  }

  return respuesta.json();
}

/** Precios de varias tenencias. */
export async function traerPrecios(inversiones) {
  const pedidos = new Map();
  for (const inv of inversiones) {
    if (!vaPorElProxy(inv.tipo) || !inv.ticker) continue;
    const mercado = mercadoDe(inv);
    pedidos.set(`${mercado}:${String(inv.ticker).toUpperCase()}`, {
      ticker: String(inv.ticker).toUpperCase(),
      mercado,
    });
  }

  const precios = {};
  const sinCobertura = [];
  let error = null;

  for (const [clave, { ticker, mercado }] of pedidos) {
    try {
      const datos = await pedir(
        `/api/precio?ticker=${encodeURIComponent(ticker)}&mercado=${mercado}`
      );
      if (Number.isFinite(datos?.precio)) {
        precios[clave] = datos;
        guardar(clave, datos.precio, datos.moneda);
      } else {
        sinCobertura.push(ticker);
      }
    } catch (problema) {
      if (problema.sinConfigurar || problema.sinSesion || problema.demasiadosPedidos) {
        error = problema.message;
        break;
      }
      if (problema.sinCobertura) sinCobertura.push(ticker);
      else {
        error = problema.message;
        break;
      }
    }
  }

  return { precios, sinCobertura, error };
}

/** Serie de cierres para el gráfico de un activo. */
export async function traerHistorico(ticker, mercado, dias = 90) {
  const datos = await pedir(
    `/api/historico?ticker=${encodeURIComponent(ticker)}&mercado=${mercado}&dias=${dias}`
  );
  return Array.isArray(datos?.puntos) ? datos.puntos : [];
}
