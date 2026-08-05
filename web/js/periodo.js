// El período que miran todas las pantallas.
//
// Un período es siempre un par de fechas cerradas en YYYY-MM-DD, más una
// etiqueta para mostrar. Las pantallas nunca calculan fechas: reciben los
// movimientos ya acotados y la etiqueta ya escrita.

import { fechaCorta } from "./format.js";

export const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

/** YYYY-MM-DD en hora local: toISOString() usa UTC y corre un día. */
function iso(anio, mes, dia) {
  return `${anio}-${String(mes + 1).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

/**
 * Un mes entero.
 * @param {number} anio
 * @param {number} mes  0 = enero, como en Date
 */
export function mes(anio, numeroDeMes) {
  // Día 0 del mes siguiente = último día de este. Sirve igual para febrero de
  // un año bisiesto, sin tener que saber nada de bisiestos.
  const ultimo = new Date(anio, numeroDeMes + 1, 0).getDate();
  const esteAnio = new Date().getFullYear();

  return {
    tipo: "mes",
    anio,
    mes: numeroDeMes,
    desde: iso(anio, numeroDeMes, 1),
    hasta: iso(anio, numeroDeMes, ultimo),
    etiqueta: anio === esteAnio ? MESES[numeroDeMes] : `${MESES[numeroDeMes]} ${anio}`,
  };
}

export function mesActual(hoy = new Date()) {
  return mes(hoy.getFullYear(), hoy.getMonth());
}

/**
 * Un rango suelto. Si vienen dados vuelta se corrigen solos: es más amable que
 * un cartel de error por algo que se arregla con un swap.
 */
export function rango(desde, hasta) {
  const [a, b] = desde <= hasta ? [desde, hasta] : [hasta, desde];
  return {
    tipo: "rango",
    desde: a,
    hasta: b,
    etiqueta: a === b ? fechaCorta(a) : `${fechaCorta(a)} – ${fechaCorta(b)}`,
  };
}

/** Para resaltar el mes elegido en el panel. */
export function esMismoMes(periodo, anio, numeroDeMes) {
  return periodo.tipo === "mes" && periodo.anio === anio && periodo.mes === numeroDeMes;
}

// --------------------------------------------------------------------------
// Cuentas sobre el período
// --------------------------------------------------------------------------

function aFecha(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d);
}

/** Corre una fecha N días (N puede ser negativo). */
function correr(fechaISO, cuantos) {
  const f = aFecha(fechaISO);
  // Se suma sobre los campos locales, no sobre milisegundos: con cambio de
  // horario, un día no siempre tiene 24 horas.
  return isoDe(new Date(f.getFullYear(), f.getMonth(), f.getDate() + cuantos));
}

function isoDe(fecha) {
  return iso(fecha.getFullYear(), fecha.getMonth(), fecha.getDate());
}

/** Días que abarca el período, contando las dos puntas. */
export function dias({ desde, hasta }) {
  const a = aFecha(desde);
  const b = aFecha(hasta);
  // La resta va en UTC para que el cambio de horario no meta un ±1 hora que
  // redondee mal el día.
  const ms =
    Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) -
    Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
  return ms / 86400000 + 1;
}

/**
 * Días del período que ya pasaron. Importa para el promedio diario: el 5 de
 * agosto, dividir lo gastado por los 31 días del mes daría un promedio que no
 * es el ritmo real, sino uno mucho más bajo.
 */
export function diasTranscurridos(periodo, hoy = new Date()) {
  const corte = isoDe(hoy);
  if (corte < periodo.desde) return 1; // período futuro: no hay nada que promediar
  return Math.max(1, dias({ desde: periodo.desde, hasta: corte < periodo.hasta ? corte : periodo.hasta }));
}

/**
 * Las fechas del período, una por día, hasta hoy si todavía no terminó: la
 * línea de evolución no puede dibujar una recta plana sobre los días que
 * faltan vivir.
 */
export function fechasDe(periodo, hoy = new Date()) {
  const corte = isoDe(hoy) < periodo.hasta ? isoDe(hoy) : periodo.hasta;
  if (corte < periodo.desde) return [];

  const fechas = [];
  for (let f = periodo.desde; f <= corte; f = correr(f, 1)) fechas.push(f);
  return fechas;
}

/**
 * El período anterior equivalente: el mes de antes si es un mes, o el mismo
 * largo pegado atrás si es un rango.
 */
export function anterior(periodo) {
  if (periodo.tipo === "mes") {
    return periodo.mes === 0 ? mes(periodo.anio - 1, 11) : mes(periodo.anio, periodo.mes - 1);
  }
  const largo = dias(periodo);
  const hasta = correr(periodo.desde, -1);
  return rango(correr(hasta, -(largo - 1)), hasta);
}
