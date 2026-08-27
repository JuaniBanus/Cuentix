// Score de salud financiera, de 0 a 100.

import { sumar } from "./format.js";
import { progresoDe } from "./objetivos.js";


const AHORRO_MALO = 0;
const AHORRO_BUENO = 0.2;

const GASTO_BUENO = 0.5;
const GASTO_MALO = 1.0;

const LIQUIDEZ_MALA = 0;
const LIQUIDEZ_BUENA = 6;

const VARIACION_BUENA = 0.1;
const VARIACION_MALA = 0.5;

export const PESOS = {
  ahorro: 30,
  gasto: 25,
  liquidez: 20,
  estabilidad: 15,
  objetivos: 10,
};

export const ETIQUETAS = {
  ahorro: "Tasa de ahorro",
  gasto: "Nivel de gasto",
  liquidez: "Liquidez",
  estabilidad: "Estabilidad",
  objetivos: "Objetivos",
};

/** Puntúa un valor interpolando entre `malo` (0) y `bueno` (100). */
function tramo(valor, malo, bueno) {
  if (bueno === malo) return 0;
  const proporcion = (valor - malo) / (bueno - malo);
  return Math.max(0, Math.min(100, proporcion * 100));
}

const redondear = (n) => Math.round(n * 10) / 10;

/** Calcula el score y su desglose. */
export function calcularSalud({
  movimientos = [],
  movimientosPrevios = [],
  historialAhorros = [],
  objetivos = [],
  moneda,
}) {
  const delPeriodo = movimientos.filter((m) => m.moneda === moneda);
  const previos = movimientosPrevios.filter((m) => m.moneda === moneda);

  const ingresos = sumar(delPeriodo.filter((m) => m.tipo === "ingreso"));
  const gastos = sumar(delPeriodo.filter((m) => m.tipo === "gasto"));
  const ahorros = sumar(delPeriodo.filter((m) => m.tipo === "ahorro"));
  const gastosPrevios = sumar(previos.filter((m) => m.tipo === "gasto"));

  const ahorroAcumulado = sumar(historialAhorros.filter((m) => m.moneda === moneda));

  const componentes = [];
  const noAplican = [];

  if (ingresos > 0) {
    const tasa = ahorros / ingresos;
    componentes.push({
      clave: "ahorro",
      puntos: tramo(tasa, AHORRO_MALO, AHORRO_BUENO),
      detalle: `Ahorrás el ${redondear(tasa * 100)}% de lo que entra`,
      referencia: `la referencia es ${AHORRO_BUENO * 100}%`,
      valor: tasa,
    });
  } else {
    noAplican.push({ clave: "ahorro", motivo: "no hay ingresos registrados en el período" });
  }

  if (ingresos > 0) {
    const nivel = gastos / ingresos;
    componentes.push({
      clave: "gasto",
      puntos: tramo(nivel, GASTO_MALO, GASTO_BUENO),
      detalle: `Gastás el ${redondear(nivel * 100)}% de lo que entra`,
      referencia: `por debajo de ${GASTO_BUENO * 100}% puntúa completo`,
      valor: nivel,
    });
  } else {
    noAplican.push({ clave: "gasto", motivo: "no hay ingresos registrados en el período" });
  }

  if (gastos > 0 || ahorroAcumulado > 0) {
    const meses = gastos > 0 ? ahorroAcumulado / gastos : LIQUIDEZ_BUENA;
    componentes.push({
      clave: "liquidez",
      puntos: tramo(meses, LIQUIDEZ_MALA, LIQUIDEZ_BUENA),
      detalle:
        gastos > 0
          ? `Lo ahorrado cubre ${redondear(meses)} ${redondear(meses) === 1 ? "mes" : "meses"} de gastos`
          : "Tenés ahorro y no registraste gastos este período",
      referencia: `el colchón recomendado es de ${LIQUIDEZ_BUENA} meses`,
      valor: meses,
    });
  } else {
    noAplican.push({ clave: "liquidez", motivo: "no hay gastos ni ahorros para comparar" });
  }

  if (gastosPrevios > 0) {
    const variacion = Math.abs(gastos - gastosPrevios) / gastosPrevios;
    componentes.push({
      clave: "estabilidad",
      puntos: tramo(variacion, VARIACION_MALA, VARIACION_BUENA),
      detalle: `Tu gasto se movió ${redondear(variacion * 100)}% respecto del período anterior`,
      referencia: `hasta ${VARIACION_BUENA * 100}% se considera estable`,
      valor: variacion,
    });
  } else {
    noAplican.push({ clave: "estabilidad", motivo: "no hay período anterior con qué comparar" });
  }

  const activos = objetivos.filter((o) => o.estado !== "pausado" && o.moneda === moneda);
  if (activos.length) {
    const progresos = activos.map((o) => progresoDe(o, historialAhorros).porcentaje);
    const promedio = progresos.reduce((t, p) => t + p, 0) / progresos.length;
    componentes.push({
      clave: "objetivos",
      puntos: Math.max(0, Math.min(100, promedio)),
      detalle:
        activos.length === 1
          ? `Vas al ${redondear(promedio)}% de tu objetivo`
          : `Vas al ${redondear(promedio)}% promedio de tus ${activos.length} objetivos`,
      referencia: "cuenta el avance sobre la meta de cada uno",
      valor: promedio / 100,
    });
  } else {
    noAplican.push({ clave: "objetivos", motivo: "no tenés objetivos activos en esta moneda" });
  }

  const faltantes = noAplican.map((n) => ({ ...n, etiqueta: ETIQUETAS[n.clave] }));

  if (!componentes.length) {
    return { score: null, componentes: [], noAplican: faltantes, banda: null };
  }

  const pesoTotal = componentes.reduce((t, c) => t + PESOS[c.clave], 0);
  const score = componentes.reduce((t, c) => t + c.puntos * PESOS[c.clave], 0) / pesoTotal;

  for (const c of componentes) {
    c.peso = PESOS[c.clave];
    c.pesoEfectivo = (PESOS[c.clave] / pesoTotal) * 100;
    c.aporte = (c.puntos * PESOS[c.clave]) / pesoTotal;
    c.etiqueta = ETIQUETAS[c.clave];
    c.puntos = redondear(c.puntos);
  }

  return {
    score: Math.round(score),
    componentes,
    noAplican: faltantes,
    parcial: faltantes.length > 0,
    banda: bandaDe(score),
  };
}

const BANDAS = [
  { hasta: 40, nombre: "Necesita atención", clase: "es-baja" },
  { hasta: 60, nombre: "Justa", clase: "es-media" },
  { hasta: 80, nombre: "Buena", clase: "es-buena" },
  { hasta: 101, nombre: "Muy buena", clase: "es-suba" },
];

export function bandaDe(score) {
  return BANDAS.find((b) => score < b.hasta) ?? BANDAS[BANDAS.length - 1];
}

/** Qué sube y qué baja el score, en castellano. */
const minuscula = (texto) => texto.charAt(0).toLowerCase() + texto.slice(1);

export function explicar({ componentes, noAplican }) {
  if (!componentes.length) return { sube: [], baja: [], falta: [] };

  const ordenados = [...componentes].sort((a, b) => b.puntos - a.puntos);
  const sube = ordenados.filter((c) => c.puntos >= 70);
  const baja = ordenados.filter((c) => c.puntos < 45).reverse();

  const frase = (c) => `${c.etiqueta} (${Math.round(c.puntos)}/100), ${minuscula(c.detalle)}`;

  return {
    sube: sube.map(frase),
    baja: baja.map((c) => `${frase(c)} — ${c.referencia}`),
    falta: noAplican.map((n) => `${n.etiqueta}: ${n.motivo}`),
  };
}
