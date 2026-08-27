// Las cuentas de la pantalla Gastos.

import { serieAcumulada, totalesPorCategoria, totalPorTipo } from "./cuentas.js";
import { diasTranscurridos } from "./periodo.js";

/** Variación contra el período anterior. */
export function variacion(actual, previo) {
  if (previo === 0) return null;
  return ((actual - previo) / previo) * 100;
}

/** Promedios. El diario divide por los días que ya pasaron, no por los que tiene */
export function promedios(total, periodo, hoy = new Date()) {
  const diario = total / diasTranscurridos(periodo, hoy);
  return { diario, mensual: diario * 30 };
}

/** La categoría que más creció contra el período anterior. */
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
