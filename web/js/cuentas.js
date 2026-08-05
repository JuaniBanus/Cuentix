// Las cuentas sobre una lista de movimientos.
//
// Están separadas de data.js a propósito: son funciones puras, sin red ni
// estado, y así se pueden probar sin levantar el cliente de Supabase.
//
// Se hacen en JavaScript y no con agregaciones en SQL, igual que el bot las
// hace en Python: a escala de finanzas personales el costo es nulo y evita
// depender de las funciones de agregación de PostgREST.

import { sumar } from "./format.js";
import { fechasDe } from "./periodo.js";

/** Lo que se muestra cuando el movimiento no dice dónde quedó la plata. */
export const SIN_CUENTA = "sin especificar";

/** Agrupa por moneda: { ARS: [...], USD: [...] }. */
export function porMoneda(movimientos) {
  const grupos = {};
  for (const m of movimientos) (grupos[m.moneda] ??= []).push(m);
  return grupos;
}

/** Total por tipo dentro de una moneda. */
export function totalPorTipo(movimientos, tipo) {
  return sumar(movimientos.filter((m) => m.tipo === tipo));
}

/**
 * [{cuenta, total, porcentaje, sinDato}] para un tipo, de mayor a menor.
 *
 * El bot deja `cuenta` en null cuando el mensaje no dice dónde quedó la plata,
 * así que ese grupo existe casi siempre. Va último aunque sea el más grande:
 * "sin especificar" no es un lugar, y encabezando la lista se leería como si
 * fuera uno.
 */
export function totalesPorCuenta(movimientos, tipo) {
  const delTipo = movimientos.filter((m) => m.tipo === tipo);
  const total = sumar(delTipo);

  const acumulado = new Map();
  for (const m of delTipo) {
    const clave = (m.cuenta ?? "").trim().toLowerCase() || SIN_CUENTA;
    const centavos = Math.round(Number(m.monto) * 100);
    acumulado.set(clave, (acumulado.get(clave) ?? 0) + centavos);
  }

  return [...acumulado.entries()]
    .map(([cuenta, centavos]) => ({
      cuenta,
      total: centavos / 100,
      porcentaje: total ? (centavos / 100 / total) * 100 : 0,
      sinDato: cuenta === SIN_CUENTA,
    }))
    .sort((a, b) => a.sinDato - b.sinDato || b.total - a.total);
}

/**
 * Un punto por día del período, con lo del día y el acumulado.
 *
 * Los movimientos vienen ya filtrados por tipo y moneda: la serie no sabe de
 * gastos ni de ahorros, solo acumula lo que le den.
 *
 * Están todos los días, también los que no tuvieron movimientos: si se
 * saltearan, dos cargas separadas por dos semanas quedarían pegadas y la línea
 * mentiría sobre el ritmo.
 */
export function serieAcumulada(movimientos, periodo, hoy = new Date()) {
  const porDia = new Map();
  for (const m of movimientos) {
    const centavos = Math.round(Number(m.monto) * 100);
    porDia.set(m.fecha, (porDia.get(m.fecha) ?? 0) + centavos);
  }

  let acumulado = 0;
  return fechasDe(periodo, hoy).map((fecha) => {
    const delDia = porDia.get(fecha) ?? 0;
    acumulado += delDia;
    return { fecha, delDia: delDia / 100, acumulado: acumulado / 100 };
  });
}

/** [{categoria, total, porcentaje}] de mayor a menor, para un tipo y moneda. */
export function totalesPorCategoria(movimientos, tipo) {
  const delTipo = movimientos.filter((m) => m.tipo === tipo);
  const total = sumar(delTipo);

  const acumulado = new Map();
  for (const m of delTipo) {
    const centavos = Math.round(Number(m.monto) * 100);
    acumulado.set(m.categoria, (acumulado.get(m.categoria) ?? 0) + centavos);
  }

  return [...acumulado.entries()]
    .map(([categoria, centavos]) => ({
      categoria,
      total: centavos / 100,
      porcentaje: total ? (centavos / 100 / total) * 100 : 0,
    }))
    .sort((a, b) => b.total - a.total);
}
