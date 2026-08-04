// Formato de montos y fechas, colores de categoría, y el estado del ojo.

// Paleta categórica validada contra la superficie #232532 con el validador de
// la guía de visualización: los seis checks pasan (banda de luminosidad, croma,
// separación para daltonismo, piso de visión normal y contraste).
//
// El primer color es el acento exacto de la marca. Los otros cinco se generaron
// a la misma luminosidad en OKLCH, porque la rampa original —seis variantes del
// mismo violeta— daba ΔE 9.9 entre pares adyacentes, por debajo del piso de 15:
// dos categorías que nadie puede distinguir.
export const COLORES = [
  "#9184d9",
  "#05a085",
  "#c27405",
  "#d05a8e",
  "#0290e1",
  "#689b1e",
];

// Para la 7ª categoría en adelante. Los tonos no se ciclan —repetir el violeta
// diría "esta es la misma categoría que la primera"—: el resto se agrupa en
// "otros" con este gris, que se lee como "no es una categoría más".
export const COLOR_OTROS = "#75798c";

export const TOPE_CATEGORIAS = 6;

const SIMBOLOS = { ARS: "$", USD: "US$", EUR: "€" };

// Un solo interruptor para toda la app.
let oculto = false;

export const montosOcultos = () => oculto;
export const alternarOcultos = () => (oculto = !oculto);

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
  const fecha = new Date(a, m - 1, d);
  const hoy = new Date();
  const opciones = { day: "numeric", month: "short" };
  if (a !== hoy.getFullYear()) opciones.year = "numeric";
  return fecha.toLocaleDateString("es-AR", opciones).replace(".", "");
}

/** Primer día del mes actual, en YYYY-MM-DD local (no UTC, que corre un día). */
export function inicioDeMes(hoy = new Date()) {
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-01`;
}

export function hoyISO(hoy = new Date()) {
  const mes = String(hoy.getMonth() + 1).padStart(2, "0");
  const dia = String(hoy.getDate()).padStart(2, "0");
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

export function nombreDelMes(hoy = new Date()) {
  return hoy.toLocaleDateString("es-AR", { month: "long" });
}

/** Escapa lo que venga de la base antes de meterlo en innerHTML. */
export function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
