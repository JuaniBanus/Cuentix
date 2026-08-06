// Score de salud financiera, de 0 a 100.
//
// ============================ POR QUÉ ASÍ ============================
//
// El cálculo es DETERMINISTA y vive acá, en el navegador: mismos movimientos,
// mismo número, siempre. No pasa por Gemini ni por ningún modelo. Un puntaje
// que cambia solo entre dos consultas iguales no se puede auditar, y un número
// sobre la propia plata que no se puede auditar no sirve para decidir nada.
//
// Todo se mide dentro de UNA moneda, como el resto de la app: mezclar pesos y
// dólares daría un cociente sin significado.
//
// ============================ LA FÓRMULA ============================
//
// Cinco componentes, cada uno puntuado de 0 a 100 y después promediado con su
// peso. Los pesos suman 100:
//
//   Tasa de ahorro     30   ahorro / ingresos del período
//   Nivel de gasto     25   gasto / ingresos del período
//   Liquidez           20   cuántos meses de gasto cubre lo ahorrado
//   Estabilidad        15   cuánto varió el gasto contra el mes anterior
//   Objetivos          10   progreso promedio de los objetivos activos
//
// Cada componente se puntúa interpolando linealmente entre un valor "malo"
// (0 puntos) y uno "bueno" (100 puntos), recortando fuera de ese rango. Los
// umbrales están abajo, cada uno con el motivo por el que es ese y no otro.
//
// COMPONENTES QUE NO APLICAN
//
// Si falta el dato para calcular uno —no hay ingresos cargados, no hay mes
// anterior, no hay objetivos—, ese componente NO se puntúa con cero: se saca
// del promedio y los pesos restantes se renormalizan. Es la diferencia entre
// "gastás más de lo que ganás" y "no me dijiste cuánto ganás", y meterlas en
// la misma bolsa daría un score malo a quien simplemente no cargó los sueldos.
// Cuáles quedaron afuera se devuelve en `noAplican` para poder decirlo.
//
// El peso relativo de los que sí aplican se mantiene: si solo hay dos
// componentes, de pesos 30 y 20, el score es (p30*30 + p20*20) / 50.

import { sumar } from "./format.js";
import { progresoDe } from "./objetivos.js";

// --- Umbrales -------------------------------------------------------------
//
// Están todos acá arriba y con nombre para que se puedan discutir y cambiar
// sin leer el código: son decisiones de criterio, no verdades.

// Regla 50/30/20: 20% de ahorro sobre ingresos es la referencia clásica de
// finanzas personales. Ahorrar más está muy bien, pero no suma más puntos:
// arriba de ese punto el score dejaría de distinguir otras cosas.
const AHORRO_MALO = 0;
const AHORRO_BUENO = 0.2;

// De la misma regla: gastar la mitad de lo que entra deja margen para todo lo
// demás. Gastar el 100% o más significa que no queda nada, y ahí el componente
// vale 0 por más que el resto esté bien.
const GASTO_BUENO = 0.5;
const GASTO_MALO = 1.0;

// Fondo de emergencia: la recomendación habitual es de 3 a 6 meses de gastos.
// Se toma 6 como el techo del puntaje y 0 como el piso.
const LIQUIDEZ_MALA = 0;
const LIQUIDEZ_BUENA = 6;

// Cuánto puede moverse el gasto de un mes a otro sin que se vuelva
// impredecible. Un 10% es ruido normal; a partir del 50% el mes dejó de
// parecerse al anterior y presupuestar se vuelve adivinar.
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

/**
 * Puntúa un valor interpolando entre `malo` (0) y `bueno` (100).
 *
 * Funciona en los dos sentidos: si `malo` es mayor que `bueno` —como en el
 * nivel de gasto, donde más alto es peor— la pendiente se invierte sola.
 */
function tramo(valor, malo, bueno) {
  if (bueno === malo) return 0;
  const proporcion = (valor - malo) / (bueno - malo);
  return Math.max(0, Math.min(100, proporcion * 100));
}

const redondear = (n) => Math.round(n * 10) / 10;

/**
 * Calcula el score y su desglose.
 *
 * @param {object} datos
 * @param {Array}  datos.movimientos      los del período que se mira
 * @param {Array}  datos.movimientosPrevios  los del período anterior
 * @param {Array}  datos.historialAhorros  todos los ahorros, sin acotar
 * @param {Array}  datos.objetivos
 * @param {string} datos.moneda
 * @returns {{score: number|null, componentes: Array, noAplican: Array, banda: object}}
 */
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

  // Stock, no flujo: lo ahorrado en toda la historia es lo que respalda los
  // gastos de los próximos meses.
  const ahorroAcumulado = sumar(historialAhorros.filter((m) => m.moneda === moneda));

  const componentes = [];
  const noAplican = [];

  // --- 1. Tasa de ahorro ---
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

  // --- 2. Nivel de gasto ---
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

  // --- 3. Liquidez ---
  // Sin gastos en el período no hay con qué dividir. Tener ahorro y no gastar
  // nada es buena señal, así que puntúa completo; sin ahorro ni gasto no hay
  // nada que medir y el componente no aplica.
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

  // --- 4. Estabilidad ---
  if (gastosPrevios > 0) {
    const variacion = Math.abs(gastos - gastosPrevios) / gastosPrevios;
    componentes.push({
      clave: "estabilidad",
      puntos: tramo(variacion, VARIACION_MALA, VARIACION_BUENA),
      // "se movió" y no "subió"/"bajó": este componente puntúa lo PREDECIBLE,
      // no la dirección. Un gasto que bajó 40% puntúa igual de mal que uno que
      // subió 40%, y decir "bajó" entre las cosas que sostienen el score se
      // leería como un elogio a algo que en realidad lo está bajando.
      detalle: `Tu gasto se movió ${redondear(variacion * 100)}% respecto del período anterior`,
      referencia: `hasta ${VARIACION_BUENA * 100}% se considera estable`,
      valor: variacion,
    });
  } else {
    noAplican.push({ clave: "estabilidad", motivo: "no hay período anterior con qué comparar" });
  }

  // --- 5. Objetivos ---
  // Solo los activos: un objetivo pausado no dice nada del mes, y los
  // completados quedan al 100% para siempre e inflarían el promedio.
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

  // Las etiquetas se agregan acá también y no solo en el return de abajo: sin
  // esto, el caso "no se pudo calcular nada" salía con los nombres en
  // undefined, que es justo cuando la lista de faltantes es lo único que se
  // muestra.
  const faltantes = noAplican.map((n) => ({ ...n, etiqueta: ETIQUETAS[n.clave] }));

  if (!componentes.length) {
    return { score: null, componentes: [], noAplican: faltantes, banda: null };
  }

  // Promedio ponderado sobre los que sí aplican. Dividir por la suma de sus
  // pesos —y no por 100— es lo que hace que sacar un componente no hunda el
  // score de quien simplemente no tiene ese dato.
  const pesoTotal = componentes.reduce((t, c) => t + PESOS[c.clave], 0);
  const score = componentes.reduce((t, c) => t + c.puntos * PESOS[c.clave], 0) / pesoTotal;

  // Cuánto aporta cada uno al número final, para poder mostrarlo sumando.
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
    // Con componentes afuera, el número sale de una parte de la fórmula. Un 71
    // calculado sobre dos de cinco no es lo mismo que un 71 completo, y la
    // tarjeta tiene que poder decirlo al lado del número y no solo abajo.
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

/**
 * Qué sube y qué baja el score, en castellano.
 *
 * Se arma con los mismos números del desglose y no con un modelo: si el texto
 * dijera algo distinto de lo que muestran las barras, el panel se contradiría
 * a sí mismo.
 */
const minuscula = (texto) => texto.charAt(0).toLowerCase() + texto.slice(1);

export function explicar({ componentes, noAplican }) {
  if (!componentes.length) return { sube: [], baja: [], falta: [] };

  const ordenados = [...componentes].sort((a, b) => b.puntos - a.puntos);
  // 70 y 45 no son bandas del score: son el corte para decidir de qué vale la
  // pena hablar. Un componente en 60 no es ni un logro ni un problema.
  const sube = ordenados.filter((c) => c.puntos >= 70);
  const baja = ordenados.filter((c) => c.puntos < 45).reverse();

  // Cada frase lleva adelante el componente y su puntaje. Sin eso, "tu gasto
  // se movió 10,7%" no dice por sí sola si está entre lo bueno o lo malo, y
  // el mismo texto podría aparecer en cualquiera de las dos listas.
  const frase = (c) => `${c.etiqueta} (${Math.round(c.puntos)}/100), ${minuscula(c.detalle)}`;

  return {
    sube: sube.map(frase),
    baja: baja.map((c) => `${frase(c)} — ${c.referencia}`),
    falta: noAplican.map((n) => `${n.etiqueta}: ${n.motivo}`),
  };
}
