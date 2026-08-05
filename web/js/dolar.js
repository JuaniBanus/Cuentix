// Cotización del dólar oficial, de dolarapi.com.
//
// Es pública y sin clave, así que se puede pedir desde el navegador: manda
// Access-Control-Allow-Origin: *.
//
// Se cachea por media hora en dos niveles: en memoria mientras la pestaña vive
// y en localStorage entre visitas. El oficial se mueve una vez por día, así que
// pedirla en cada render sería una llamada por nada.

const URL = "https://dolarapi.com/v1/dolares/oficial";
const CLAVE = "cuentix:dolar";
const VIGENCIA = 30 * 60 * 1000;
const ESPERA = 8000;

let enMemoria = null;

export class SinCotizacion extends Error {
  constructor() {
    super("No pude traer la cotización del dólar.");
    this.name = "SinCotizacion";
  }
}

function guardar(cotizacion) {
  enMemoria = cotizacion;
  try {
    localStorage.setItem(CLAVE, JSON.stringify(cotizacion));
  } catch {
    // Modo incógnito: vale para esta pestaña y listo.
  }
}

function guardada() {
  if (enMemoria) return enMemoria;
  try {
    const crudo = localStorage.getItem(CLAVE);
    if (!crudo) return null;
    const cotizacion = JSON.parse(crudo);
    return Number.isFinite(cotizacion?.venta) ? cotizacion : null;
  } catch {
    return null;
  }
}

const estaFresca = (cotizacion, ahora) => ahora - (cotizacion?.traidaEn ?? 0) < VIGENCIA;

/**
 * La cotización, del caché si sigue fresca o de la API si no.
 *
 * Si la API no responde pero hay una guardada, se devuelve esa marcada como
 * vencida: un dólar de ayer sirve bastante más que ningún dólar, siempre que
 * la pantalla diga de cuándo es.
 *
 * @returns {Promise<{compra: number, venta: number, fecha: string, traidaEn: number, vencida: boolean}>}
 * @throws {SinCotizacion} si falla y no hay nada guardado.
 */
export async function traerCotizacion({ ahora = Date.now() } = {}) {
  const previa = guardada();
  if (previa && estaFresca(previa, ahora)) return { ...previa, vencida: false };

  try {
    const respuesta = await fetch(URL, { signal: AbortSignal.timeout(ESPERA) });
    if (!respuesta.ok) throw new SinCotizacion();

    const datos = await respuesta.json();
    // La API podría cambiar o devolver algo raro: sin un número usable, mejor
    // caer al caché que dividir por undefined y llenar la pantalla de NaN.
    if (!Number.isFinite(datos?.venta) || datos.venta <= 0) throw new SinCotizacion();

    const cotizacion = {
      compra: Number(datos.compra) || Number(datos.venta),
      venta: Number(datos.venta),
      fecha: String(datos.fechaActualizacion ?? ""),
      traidaEn: ahora,
    };
    guardar(cotizacion);
    return { ...cotizacion, vencida: false };
  } catch {
    if (previa) return { ...previa, vencida: true };
    throw new SinCotizacion();
  }
}
