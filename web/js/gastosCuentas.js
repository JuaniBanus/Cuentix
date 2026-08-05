// Las cuentas de la pantalla Gastos.
//
// Puras y sin DOM, para poder probarlas: son las que más fácil se equivocan en
// silencio (un promedio dividido por el número de días equivocado no rompe
// nada, solo miente).

import { serieAcumulada, totalesPorCategoria, totalPorTipo } from "./cuentas.js";
import { diasTranscurridos } from "./periodo.js";

/**
 * Variación contra el período anterior.
 *
 * Cuando antes no se gastó nada no hay porcentaje posible —dividir por cero da
 * infinito, y "+∞%" no le dice nada a nadie—: se devuelve null y la pantalla
 * escribe "sin gastos en julio".
 */
export function variacion(actual, previo) {
  if (previo === 0) return null;
  return ((actual - previo) / previo) * 100;
}

/**
 * Promedios. El diario divide por los días que ya pasaron, no por los que tiene
 * el período: el 5 de agosto llevás 5 días de gasto, no 31.
 *
 * El mensual es el diario por 30, o sea a qué ritmo mensual vas. En un mes
 * terminado da casi el total; en uno en curso, la proyección.
 */
export function promedios(total, periodo, hoy = new Date()) {
  const diario = total / diasTranscurridos(periodo, hoy);
  return { diario, mensual: diario * 30 };
}

/**
 * La categoría que más creció contra el período anterior.
 *
 * Se ordena por cuánto creció en pesos y no en porcentaje: una categoría que
 * pasó de $10 a $100 creció 900% y encabezaría el ranking para siempre, aunque
 * sean noventa pesos. El porcentaje igual se devuelve, para mostrarlo.
 *
 * `esNueva` marca las que antes no existían: ahí no hay porcentaje, y decir
 * "nueva" es más claro que cualquier número.
 */
export function laQueMasCrecio(categoriasActuales, categoriasPrevias) {
  const previas = new Map(categoriasPrevias.map((c) => [c.categoria, c.total]));

  const crecimientos = categoriasActuales
    .map((c) => {
      const antes = previas.get(c.categoria) ?? 0;
      return {
        categoria: c.categoria,
        total: c.total,
        crecimiento: c.total - antes,
        porcentaje: antes === 0 ? null : ((c.total - antes) / antes) * 100,
        esNueva: antes === 0,
      };
    })
    .filter((c) => c.crecimiento > 0)
    .sort((a, b) => b.crecimiento - a.crecimiento);

  return crecimientos[0] ?? null;
}

/** Todo lo que la pantalla necesita, calculado de una vez. */
export function resumenDeGastos({ movimientos, previos, periodo, hoy = new Date() }) {
  const total = totalPorTipo(movimientos, "gasto");
  const totalPrevio = totalPorTipo(previos, "gasto");
  const categorias = totalesPorCategoria(movimientos, "gasto");

  return {
    total,
    totalPrevio,
    categorias,
    serie: serieAcumulada(movimientos.filter((m) => m.tipo === "gasto"), periodo, hoy),
    variacion: variacion(total, totalPrevio),
    ...promedios(total, periodo, hoy),
    masConsume: categorias[0] ?? null,
    masCrecio: laQueMasCrecio(categorias, totalesPorCategoria(previos, "gasto")),
  };
}
