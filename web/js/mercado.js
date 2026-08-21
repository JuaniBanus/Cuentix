// Precios de mercado para acciones, ETFs, CEDEARs y bonos.
//
// Habla con el proxy del bot (/api/precio, /api/historico), que es quien tiene
// la clave del proveedor. La cripto NO pasa por acá: sale de CoinGecko, que es
// pública y con CORS, y por eso vive en precios.js.
//
// ============================ EL MERCADO ============================
//
// Cada posición se consulta en el mercado que corresponde a SU moneda:
//
//   posición en ARS -> mercado "ar" (BYMA, vía Data912)
//   posición en USD -> mercado "us" (NASDAQ/NYSE, vía Twelve Data)
//
// No es una preferencia: AAPL existe en los dos y son activos distintos. El
// CEDEAR cotiza ~$24.650 y la acción ~US$312. Valuar una tenencia comprada en
// pesos contra el precio en dólares daría una ganancia inventada de miles por
// ciento. La moneda de la compra es lo que dice cuál de los dos comprás.
//
// ======================= ÚLTIMO PRECIO CONOCIDO =======================
//
// Cada precio que llega se guarda en localStorage con su fecha. Cuando el
// proveedor no cubre un activo, o el backend está dormido, la pantalla puede
// mostrar el último precio conocido diciendo de cuándo es, en vez de caer al
// precio de compra como si nada hubiera pasado. Un precio de ayer es un dato;
// un precio de ayer presentado como el de hoy es un error.

import { BACKEND_URL } from "./config.js";
import { sesionActual } from "./data.js";

const CLAVE_CACHE = "cuentix:precios-mercado";

// Cuánto vale un precio guardado antes de considerarlo "viejo" a la hora de
// mostrarlo. No borra nada: solo decide si la pantalla aclara la fecha.
const FRESCO_MS = 60 * 60 * 1000; // 1 hora

const ESPERA_MS = 90_000;

/** Qué mercado le corresponde a una tenencia, por su moneda. */
export function mercadoDe(inversion) {
  return inversion?.moneda === "ARS" ? "ar" : "us";
}

/** Los tipos que se valúan por el proxy. La cripto va por CoinGecko. */
export function vaPorElProxy(tipo) {
  return ["accion", "etf", "cedear", "bono", "fci"].includes(tipo);
}

// --------------------------------------------------------------------------
// Último precio conocido
// --------------------------------------------------------------------------

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
    // Modo privado o storage lleno: se pierde el histórico local y ya.
  }
}

/**
 * El último precio que supimos de este activo, si alguna vez lo supimos.
 *
 * @returns {{precio: number, moneda: string, cuando: number, fresco: boolean}|null}
 */
export function ultimoConocido(ticker, mercado) {
  const guardado = leerGuardados()[`${mercado}:${String(ticker).toUpperCase()}`];
  if (!guardado || !Number.isFinite(guardado.precio)) return null;
  return { ...guardado, fresco: Date.now() - guardado.cuando < FRESCO_MS };
}

// --------------------------------------------------------------------------
// Consultas al proxy
// --------------------------------------------------------------------------

async function pedir(ruta) {
  if (!BACKEND_URL) throw new Error("Falta configurar BACKEND_URL en config.js.");

  // El proxy pide sesión desde que se cerró el agujero de cuota: sin token,
  // cualquiera con la URL podía quemar las 700 llamadas diarias del proveedor
  // y dejar esta pantalla con precios viejos sin explicación.
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
    // 400 y 502 significan "este activo no está cubierto"; 503, "falta la
    // clave". La pantalla los trata distinto: uno es por activo y el otro es
    // de configuración y afecta a todos.
    error.sinCobertura = respuesta.status === 400 || respuesta.status === 502;
    error.sinConfigurar = respuesta.status === 503;
    error.sinSesion = respuesta.status === 401;
    // 429 es cupo, no falta de cobertura: reintentar en unos segundos anda.
    // Marcarlo aparte evita que la pantalla diga "no cubierto" sobre un activo
    // que sí lo está.
    if (respuesta.status === 429) {
      error.demasiadosPedidos = true;
      error.esperaSegundos = Number(respuesta.headers.get("retry-after")) || 60;
    }
    throw error;
  }

  return respuesta.json();
}

/**
 * Precios de varias tenencias.
 *
 * Devuelve un mapa por `mercado:TICKER` para que una acción y su CEDEAR no se
 * pisen entre sí, y nunca lanza: los activos que fallan quedan listados en
 * `sinCobertura` y la pantalla decide qué mostrar.
 */
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

  // En serie y no en paralelo: el proxy tiene un tope por minuto y dispararle
  // diez pedidos juntos garantiza chocarlo. Con el caché del backend, la
  // segunda vuelta no cuesta nada.
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
      // Tres motivos distintos para cortar en seco en vez de seguir con el
      // resto: falta la clave en el servidor, venció la sesión, o se agotó el
      // cupo por minuto. Ninguno mejora pidiendo el activo siguiente, y con el
      // cupo insistir es lo peor que se puede hacer.
      if (problema.sinConfigurar || problema.sinSesion || problema.demasiadosPedidos) {
        error = problema.message;
        break;
      }
      // Esto sí es del activo: los demás pueden andar.
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
