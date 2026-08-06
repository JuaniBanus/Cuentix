// Precios de mercado de las tenencias.
//
// Hoy solo cripto, vía CoinGecko: su endpoint /simple/price es gratuito, no
// pide clave y manda Access-Control-Allow-Origin, así que se puede llamar
// desde el navegador sin proxy.
//
// Para acciones, CEDEARs, bonos y FCI NO hay precio: ninguna API gratuita con
// CORS cubre el mercado argentino de forma confiable, y las de mercado
// estadounidense piden clave. Esas posiciones se muestran valuadas a su precio
// de compra y marcadas como tales. La alternativa —estimar, interpolar o
// mostrar el precio de otro activo parecido— sería inventar un número que el
// usuario leería como real.
//
// El límite del plan gratuito ronda las 30 llamadas por minuto. Como acá se
// pide UNA vez por render, con todos los ids juntos, no se roza ni de cerca.

const URL_COINGECKO = "https://api.coingecko.com/api/v3/simple/price";

const CLAVE_CACHE = "cuentix:precios-cripto";
const VIGENCIA_MS = 5 * 60 * 1000; // la cripto se mueve; 5 minutos
const TIEMPO_LIMITE_MS = 8000;

// CoinGecko identifica por su id interno, no por ticker. Este mapa cubre lo
// que alguien de acá suele tener; lo que no esté queda sin precio y se dice.
const IDS_COINGECKO = {
  BTC: "bitcoin",
  ETH: "ethereum",
  USDT: "tether",
  USDC: "usd-coin",
  DAI: "dai",
  BNB: "binancecoin",
  SOL: "solana",
  XRP: "ripple",
  ADA: "cardano",
  DOGE: "dogecoin",
  DOT: "polkadot",
  MATIC: "matic-network",
  POL: "polygon-ecosystem-token",
  AVAX: "avalanche-2",
  LINK: "chainlink",
  LTC: "litecoin",
  TRX: "tron",
  SHIB: "shiba-inu",
  UNI: "uniswap",
  ATOM: "cosmos",
  XLM: "stellar",
  NEAR: "near",
  ARB: "arbitrum",
  OP: "optimism",
  PEPE: "pepe",
  DAI2: "dai",
};

/**
 * true si el precio de este tipo sale de CoinGecko.
 *
 * Ya no significa "el único tipo con precio de mercado": las acciones, ETFs,
 * CEDEARs y bonos también se valúan, pero por el proxy del bot (mercado.js).
 * Lo que distingue a la cripto es que su fuente es pública y con CORS, así que
 * el navegador la consulta directo y sin clave.
 */
export function tienePrecioDeMercado(tipo) {
  return tipo === "cripto";
}

export function idDeCoinGecko(ticker) {
  return IDS_COINGECKO[String(ticker ?? "").trim().toUpperCase()] ?? null;
}

function leerCache() {
  try {
    const crudo = sessionStorage.getItem(CLAVE_CACHE);
    if (!crudo) return null;
    const guardado = JSON.parse(crudo);
    if (Date.now() - guardado.momento > VIGENCIA_MS) return null;
    return guardado.precios;
  } catch {
    return null;
  }
}

function guardarCache(precios) {
  try {
    sessionStorage.setItem(CLAVE_CACHE, JSON.stringify({ momento: Date.now(), precios }));
  } catch {
    // Sin storage se sigue andando, solo que se pide de nuevo en cada render.
  }
}

/**
 * Precios en USD de las criptos de la cartera.
 *
 * @param {string[]} tickers
 * @returns {Promise<{precios: Record<string, number>, sinCotizar: string[], error: string|null}>}
 *
 * Nunca lanza: si CoinGecko no responde, devuelve el error como dato y la
 * pantalla muestra las posiciones valuadas a costo. Que se caiga una API de
 * precios no puede dejar al usuario sin ver su cartera.
 */
export async function traerPreciosCripto(tickers) {
  const unicos = [...new Set(tickers.map((t) => String(t ?? "").toUpperCase()))].filter(Boolean);
  const conId = unicos.filter((t) => idDeCoinGecko(t));
  const sinCotizar = unicos.filter((t) => !idDeCoinGecko(t));

  if (!conId.length) return { precios: {}, sinCotizar, error: null };

  const cache = leerCache();
  if (cache && conId.every((t) => t in cache)) {
    return { precios: cache, sinCotizar, error: null };
  }

  const ids = conId.map(idDeCoinGecko).join(",");
  const url = `${URL_COINGECKO}?ids=${encodeURIComponent(ids)}&vs_currencies=usd`;

  const corte = new AbortController();
  const reloj = setTimeout(() => corte.abort(), TIEMPO_LIMITE_MS);
  try {
    const respuesta = await fetch(url, { signal: corte.signal });
    if (!respuesta.ok) {
      // 429 es el caso probable: demasiadas llamadas desde esta IP.
      const detalle = respuesta.status === 429
        ? "CoinGecko está limitando las consultas, probá en un minuto."
        : `CoinGecko respondió ${respuesta.status}.`;
      return { precios: {}, sinCotizar, error: detalle };
    }

    const datos = await respuesta.json();
    const precios = {};
    for (const ticker of conId) {
      const precio = datos?.[idDeCoinGecko(ticker)]?.usd;
      if (Number.isFinite(precio)) precios[ticker] = precio;
      else sinCotizar.push(ticker);
    }

    guardarCache(precios);
    return { precios, sinCotizar: [...new Set(sinCotizar)].sort(), error: null };
  } catch (err) {
    const detalle = err.name === "AbortError"
      ? "CoinGecko tardó demasiado en responder."
      : "No pude consultar los precios de cripto.";
    return { precios: {}, sinCotizar, error: detalle };
  } finally {
    clearTimeout(reloj);
  }
}
