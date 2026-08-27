// Recomendaciones sobre los gastos.

import { BACKEND_URL } from "./config.js";
import { sesionActual } from "./data.js";

export const MESES_ANALIZADOS = 6;

const TOLERANCIA_MONTO = 0.15;

const MINIMO_APARICIONES = 3;

/** "2026-08-04" -> "2026-08". */
const mesDe = (fecha) => String(fecha).slice(0, 7);

/** Normaliza el concepto para poder agrupar: minúsculas, sin acentos ni ruido. */
function clave(texto) {
  return String(texto ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const mediana = (numeros) => {
  const orden = [...numeros].sort((a, b) => a - b);
  const medio = Math.floor(orden.length / 2);
  return orden.length % 2 ? orden[medio] : (orden[medio - 1] + orden[medio]) / 2;
};

/** Cargos que se repiten mes a mes por un monto parecido. */
export function detectarRecurrentes(gastos) {
  const grupos = new Map();

  for (const g of gastos) {
    const k = clave(g.descripcion) || clave(g.categoria);
    if (!k) continue;
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(g);
  }

  const recurrentes = [];

  for (const [k, items] of grupos) {
    const meses = [...new Set(items.map((g) => mesDe(g.fecha)))].sort();
    if (meses.length < MINIMO_APARICIONES) continue;

    const tipico = mediana(items.map((g) => Math.abs(Number(g.monto))));
    if (!tipico) continue;

    const parecidos = items.filter(
      (g) => Math.abs(Math.abs(Number(g.monto)) - tipico) <= tipico * TOLERANCIA_MONTO
    );
    const mesesParecidos = [...new Set(parecidos.map((g) => mesDe(g.fecha)))].sort();
    if (mesesParecidos.length < MINIMO_APARICIONES) continue;

    const dispersion =
      (items.reduce((t, g) => t + Math.abs(Math.abs(Number(g.monto)) - tipico), 0) /
        items.length /
        tipico) *
      100;

    recurrentes.push({
      concepto: (items[0].descripcion || items[0].categoria || k).slice(0, 80),
      monto_tipico: Math.round(tipico * 100) / 100,
      veces: parecidos.length,
      meses_seguidos: rachaDeMeses(mesesParecidos),
      ultimo_mes: mesesParecidos[mesesParecidos.length - 1],
      dispersion_pct: Math.round(dispersion * 10) / 10,
      categoria: items[0].categoria ?? null,
    });
  }

  return recurrentes.sort((a, b) => b.monto_tipico - a.monto_tipico).slice(0, 20);
}

/** La racha más larga de meses consecutivos dentro de una lista "AAAA-MM". */
function rachaDeMeses(meses) {
  let mejor = 1;
  let actual = 1;

  for (let i = 1; i < meses.length; i++) {
    const [a1, m1] = meses[i - 1].split("-").map(Number);
    const [a2, m2] = meses[i].split("-").map(Number);
    const consecutivo = a2 * 12 + m2 === a1 * 12 + m1 + 1;
    actual = consecutivo ? actual + 1 : 1;
    mejor = Math.max(mejor, actual);
  }
  return mejor;
}

/** Suma por categoría: { comida: 42000, ... }. */
function porCategoria(gastos) {
  const totales = {};
  for (const g of gastos) {
    const cat = g.categoria || "sin categoría";
    totales[cat] = (totales[cat] ?? 0) + Math.abs(Number(g.monto));
  }
  return totales;
}

const redondear = (n) => Math.round(n * 100) / 100;

/** Arma el paquete de números que se le manda al análisis. */
export function armarAgregados({
  movimientos,
  previos = [],
  historial = [],
  moneda,
  etiquetaPeriodo,
}) {
  const gastos = movimientos.filter((m) => m.tipo === "gasto");
  const gastosPrevios = previos.filter((m) => m.tipo === "gasto");
  const gastosHistorial = historial.filter((m) => m.tipo === "gasto");

  const total = gastos.reduce((t, g) => t + Math.abs(Number(g.monto)), 0);
  const totalPrevio = gastosPrevios.reduce((t, g) => t + Math.abs(Number(g.monto)), 0);

  const actuales = porCategoria(gastos);
  const anteriores = porCategoria(gastosPrevios);

  const mesesEnHistorial = new Set(gastosHistorial.map((g) => mesDe(g.fecha))).size || 1;
  const acumuladoHistorial = porCategoria(gastosHistorial);

  const categorias = Object.entries(actuales)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 30)
    .map(([categoria, monto]) => {
      const antes = anteriores[categoria];
      return {
        categoria,
        total: redondear(monto),
        porcentaje: total ? (monto / total) * 100 : 0,
        variacion_pct: antes ? redondear(((monto - antes) / antes) * 100) : null,
        total_anterior: antes ? redondear(antes) : null,
        promedio_mensual: acumuladoHistorial[categoria]
          ? redondear(acumuladoHistorial[categoria] / mesesEnHistorial)
          : null,
      };
    });

  const ingresos = movimientos
    .filter((m) => m.tipo === "ingreso")
    .reduce((t, m) => t + Math.abs(Number(m.monto)), 0);

  return {
    moneda,
    periodo: etiquetaPeriodo,
    meses_analizados: mesesEnHistorial,
    total_periodo: redondear(total),
    total_anterior: gastosPrevios.length ? redondear(totalPrevio) : null,
    variacion_total_pct: totalPrevio ? redondear(((total - totalPrevio) / totalPrevio) * 100) : null,
    promedio_mensual: gastosHistorial.length
      ? redondear(gastosHistorial.reduce((t, g) => t + Math.abs(Number(g.monto)), 0) / mesesEnHistorial)
      : null,
    ingreso_periodo: ingresos ? redondear(ingresos) : null,
    categorias,
    recurrentes: detectarRecurrentes(gastosHistorial.length ? gastosHistorial : gastos),
  };
}

export class SinInsights extends Error {}

/** Le pide al bot que interprete los agregados. */
export async function pedirInsights(agregados) {
  if (!BACKEND_URL) {
    throw new SinInsights("Falta configurar la dirección del backend en config.js.");
  }

  const sesion = await sesionActual();
  if (!sesion?.access_token) throw new SinInsights("Tu sesión venció. Volvé a entrar.");

  let respuesta;
  try {
    respuesta = await fetch(`${BACKEND_URL}/insights`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${sesion.access_token}`,
      },
      body: JSON.stringify(agregados),
      signal: AbortSignal.timeout(90_000),
    });
  } catch (problema) {
    throw new SinInsights(
      problema.name === "TimeoutError"
        ? "El análisis tardó demasiado. Probá de nuevo en un momento."
        : "No pude conectarme para analizar tus gastos."
    );
  }

  if (respuesta.status === 401) throw new SinInsights("Tu sesión venció. Volvé a entrar.");
  if (!respuesta.ok) {
    throw new SinInsights("No pude analizar tus gastos ahora mismo. Probá más tarde.");
  }

  const datos = await respuesta.json().catch(() => null);
  return Array.isArray(datos?.insights) ? datos.insights : [];
}
