// Formato de montos y fechas, y el estado del ojo.

// Los colores de la dona son --cat-1 … --cat-6 y --cat-otros, y viven en el CSS
// porque cada tema tiene los suyos: los seis tonos del tema oscuro sobre blanco
// quedarían lavados. Acá solo queda cuántos hay.
export const TOPE_CATEGORIAS = 6;

const SIMBOLOS = { ARS: "$", USD: "US$", EUR: "€" };

// Un solo interruptor para toda la app.
let oculto = false;

export const montosOcultos = () => oculto;
export const alternarOcultos = () => (oculto = !oculto);

// --------------------------------------------------------------------------
// Ver todo en dólares
// --------------------------------------------------------------------------
//
// La conversión vive adentro de `monto()` y no en cada pantalla: es la única
// puerta por la que sale un número a la vista, así que alcanza con tocarla acá
// para que el botón valga en toda la app, gráficos incluidos.
//
// Las monedas se siguen sumando por separado: esto convierte lo que se MUESTRA,
// no junta varias monedas en un total. Sumarlas daría un número que depende de
// la cotización del día y que cambiaría solo.
//
// La tasa de cada moneda dice cuántos USD vale una unidad, así que convertir es
// siempre multiplicar. Para los pesos eso es 1/(ARS por USD), o sea lo mismo que
// dividir por la venta del oficial; el euro entra por la misma puerta sin que
// las pantallas tengan que saber que existe.

let enDolares = false;
let cotizacion = null;

export const verEnDolares = () => enDolares;
export const cotizacionActual = () => cotizacion;

export function fijarCotizacion(nueva) {
  cotizacion = nueva;
  // Sin cotización no se puede convertir: se vuelve a mostrar cada moneda como
  // es, en vez de dejar la app en un modo que no puede cumplir.
  if (!nueva) enDolares = false;
}

export function alternarDolares() {
  if (!cotizacion) return false;
  enDolares = !enDolares;
  return enDolares;
}

/**
 * Cuántos USD vale una unidad de `moneda`, o null si no se puede cotizar.
 *
 * Los dólares valen 1 sin depender de que haya llegado ninguna cotización: son
 * la unidad en la que se convierte.
 */
export function tasaAUSD(moneda) {
  if (moneda === "USD") return 1;
  const tasa = cotizacion?.tasas?.[moneda];
  return Number.isFinite(tasa) ? tasa : null;
}

/** true si el modo dólar está activo y esta moneda se puede convertir. */
const seConvierte = (moneda) => enDolares && moneda !== "USD" && tasaAUSD(moneda) !== null;

/**
 * El valor convertido, si corresponde.
 *
 * Una moneda sin cotización vuelve intacta: mostrarla en su moneda es preferible
 * a esconderla de un total que el usuario cree completo.
 */
export function enDolaresSiCorresponde(valor, moneda) {
  return seConvierte(moneda) ? valor * tasaAUSD(moneda) : valor;
}

/** Suma montos en centavos enteros: 8500.10 + 1200.20 en float da 9700.2999… */
export function sumar(movimientos) {
  const centavos = movimientos.reduce(
    (total, m) => total + Math.round(Number(m.monto) * 100),
    0
  );
  return centavos / 100;
}

/** 8500 -> "$8.500" · 15340.5 USD -> "US$15.340,50" (formato argentino). */
export function monto(valor, moneda = "ARS", { signo = false } = {}) {
  // El ojo tapado gana: si están ocultos, no importa en qué moneda.
  if (oculto) return "••••••";

  if (seConvierte(moneda)) {
    valor = valor * tasaAUSD(moneda);
    moneda = "USD";
  }

  const simbolo = SIMBOLOS[moneda] ?? `${moneda} `;
  const negativo = valor < 0;
  const absoluto = Math.abs(valor);

  // Sin decimales cuando son .00: la mayoría de los gastos son redondos y el
  // ",00" repetido en una lista es ruido.
  const enteros = Math.round(absoluto) === Number(absoluto.toFixed(2))
    ? absoluto.toLocaleString("es-AR", { maximumFractionDigits: 0 })
    : absoluto.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const prefijo = negativo ? "−" : signo ? "+" : "";
  return `${prefijo}${simbolo}${enteros}`;
}

/** "2026-08-04" -> "4 ago" · si es de otro año, "4 ago 2025". */
export function fechaCorta(iso) {
  const [a, m, d] = iso.split("-").map(Number);

  // Solo el nombre del mes sale del locale. Pedirle la fecha entera con año
  // devolvía "20 de dic. de 2025", que en el encabezado ocupa media pantalla.
  const nombreDeMes = new Date(a, m - 1, d)
    .toLocaleDateString("es-AR", { month: "short" })
    .replace(".", "");

  const hoy = new Date();
  return a === hoy.getFullYear() ? `${d} ${nombreDeMes}` : `${d} ${nombreDeMes} ${a}`;
}

export function hoyISO(hoy = new Date()) {
  const mes = String(hoy.getMonth() + 1).padStart(2, "0");
  const dia = String(hoy.getDate()).padStart(2, "0");
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

/** Escapa lo que venga de la base antes de meterlo en innerHTML. */
export function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
