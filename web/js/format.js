// Formato de montos y fechas, y el estado del ojo.

export const TOPE_CATEGORIAS = 6;

const SIMBOLOS = { ARS: "$", USD: "US$", EUR: "€" };

let oculto = false;

export const montosOcultos = () => oculto;
export const alternarOcultos = () => (oculto = !oculto);


let enDolares = false;
let cotizacion = null;

export const verEnDolares = () => enDolares;
export const cotizacionActual = () => cotizacion;

export function fijarCotizacion(nueva) {
  cotizacion = nueva;
  if (!nueva) enDolares = false;
}

export function alternarDolares() {
  if (!cotizacion) return false;
  enDolares = !enDolares;
  return enDolares;
}

/** Cuántos USD vale una unidad de `moneda`, o null si no se puede cotizar. */
export function tasaAUSD(moneda) {
  if (moneda === "USD") return 1;
  const tasa = cotizacion?.tasas?.[moneda];
  return Number.isFinite(tasa) ? tasa : null;
}

/** true si el modo dólar está activo y esta moneda se puede convertir. */
const seConvierte = (moneda) => enDolares && moneda !== "USD" && tasaAUSD(moneda) !== null;

/** El valor convertido, si corresponde. */
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
  if (oculto) return "••••••";

  if (seConvierte(moneda)) {
    valor = valor * tasaAUSD(moneda);
    moneda = "USD";
  }

  const simbolo = SIMBOLOS[moneda] ?? `${moneda} `;
  const negativo = valor < 0;
  const absoluto = Math.abs(valor);

  const enteros = Math.round(absoluto) === Number(absoluto.toFixed(2))
    ? absoluto.toLocaleString("es-AR", { maximumFractionDigits: 0 })
    : absoluto.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const prefijo = negativo ? "−" : signo ? "+" : "";
  return `${prefijo}${simbolo}${enteros}`;
}

/** Tapa los montos escritos adentro de un texto libre. */
export function enmascararMontos(texto) {
  return String(texto ?? "")
    .replace(/(?:US\$|U\$S|\$|€)\s?\d[\d.,]*/g, "••••••")
    .replace(/\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b/g, "••••••")
    .replace(/\b\d[\d.,]*\s?(pesos|d[óo]lares|euros)\b/gi, "•••••• $1");
}

/** "2026-08-04" -> "4 ago" · si es de otro año, "4 ago 2025". */
export function fechaCorta(iso) {
  const [a, m, d] = iso.split("-").map(Number);

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
