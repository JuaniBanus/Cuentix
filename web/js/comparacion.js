// Comparación con vos mismo: el período actual contra tu propio promedio.
//
// LA REGLA QUE ORDENA TODO EL ARCHIVO
// Se compara al usuario SOLO consigo mismo. Nunca contra otros usuarios,
// promedios del país, "gente como vos" ni ningún número externo. No es una
// limitación técnica: comparar el gasto de alguien con el de un desconocido no
// produce información útil sobre su situación, produce culpa o falsa
// tranquilidad. Lo único que dice algo verdadero sobre si este mes fue caro es
// cómo fueron los meses propios.
//
// CÓMO SE ARMA EL PROMEDIO
// Los últimos 6 meses cerrados, SIN incluir el actual: incluirlo lo acercaría
// a sí mismo y achataría la comparación justo cuando más se necesita. Un mes
// sin datos no cuenta como cero —eso hundiría el promedio— y se informa sobre
// cuántos meses se pudo calcular.

export const MESES_PROMEDIO = 6;
// Con menos de 2 meses, "tu promedio" es un mes suelto y no significa nada.
const MESES_MINIMOS = 2;
// Variaciones más chicas que esto son ruido, no una tendencia.
const RUIDO = 0.05;

function mesDe(iso) {
  return String(iso ?? "").slice(0, 7);
}

function restarMeses(mes, cuantos) {
  const [a, m] = mes.split("-").map(Number);
  const d = new Date(a, m - 1 - cuantos, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Los meses del promedio: los N cerrados anteriores al actual. */
function mesesDeReferencia(mesActual) {
  return Array.from({ length: MESES_PROMEDIO }, (_, i) => restarMeses(mesActual, i + 1));
}

function sumaPorMes(movimientos, filtro) {
  const porMes = new Map();
  for (const m of movimientos ?? []) {
    if (!filtro(m)) continue;
    const mes = mesDe(m.fecha);
    if (!mes) continue;
    porMes.set(mes, (porMes.get(mes) ?? 0) + (Number(m.monto) || 0));
  }
  return porMes;
}

/**
 * Compara un valor del mes actual contra el promedio de los meses previos.
 *
 * @returns {{actual, promedio, variacion, meses}|null} null si no alcanza la historia
 */
function contra(porMes, mesActual, actual) {
  const referencia = mesesDeReferencia(mesActual)
    .map((mes) => porMes.get(mes))
    // Un mes sin el dato NO es un cero: es un mes que no se puede promediar.
    // Contarlo como cero hundiría el promedio e inventaría una suba.
    .filter((v) => v !== undefined);

  if (referencia.length < MESES_MINIMOS) return null;

  const promedio = referencia.reduce((t, v) => t + v, 0) / referencia.length;
  if (promedio <= 0) return null;

  return {
    actual,
    promedio,
    variacion: actual / promedio - 1,
    meses: referencia.length,
  };
}

/**
 * Todas las comparaciones de un período.
 *
 * @param {Array} historial TODOS los movimientos, no solo los del período
 * @param {Array} delPeriodo los del período que se está mirando
 * @param {string} mesActual "2026-08"
 * @param {string} moneda
 */
export function comparar(historial, delPeriodo, mesActual, moneda) {
  const deLaMoneda = (historial ?? []).filter((m) => m.moneda === moneda);
  const actuales = (delPeriodo ?? []).filter((m) => m.moneda === moneda);

  const suma = (movs, tipo) =>
    movs.filter((m) => m.tipo === tipo).reduce((t, m) => t + (Number(m.monto) || 0), 0);

  const gastoActual = suma(actuales, "gasto");
  const ingresoActual = suma(actuales, "ingreso");
  const ahorroActual = suma(actuales, "ahorro");

  // 1. Gasto total.
  const gasto = contra(
    sumaPorMes(deLaMoneda, (m) => m.tipo === "gasto"),
    mesActual,
    gastoActual
  );

  // 2. Tasa de ahorro. Se compara la TASA y no el monto: ahorrar $50.000 con
  // un sueldo de $500.000 no es lo mismo que con uno de $2.000.000, y el monto
  // solo diría que cambió el sueldo.
  const porMesAhorro = sumaPorMes(deLaMoneda, (m) => m.tipo === "ahorro");
  const porMesIngreso = sumaPorMes(deLaMoneda, (m) => m.tipo === "ingreso");
  const tasas = new Map();
  for (const [mes, ingreso] of porMesIngreso) {
    if (ingreso > 0) tasas.set(mes, (porMesAhorro.get(mes) ?? 0) / ingreso);
  }
  const tasaActual = ingresoActual > 0 ? ahorroActual / ingresoActual : null;
  const tasaAhorro = tasaActual === null ? null : contra(tasas, mesActual, tasaActual);

  // 3. Por categoría. Solo las que el usuario tiene historia suficiente.
  const categorias = new Set(
    actuales.filter((m) => m.tipo === "gasto").map((m) => (m.categoria || "otros").trim())
  );
  const porCategoria = [];
  for (const categoria of categorias) {
    const actual = actuales
      .filter((m) => m.tipo === "gasto" && (m.categoria || "otros").trim() === categoria)
      .reduce((t, m) => t + (Number(m.monto) || 0), 0);

    const comparacion = contra(
      sumaPorMes(
        deLaMoneda,
        (m) => m.tipo === "gasto" && (m.categoria || "otros").trim() === categoria
      ),
      mesActual,
      actual
    );
    if (comparacion) porCategoria.push({ categoria, ...comparacion });
  }

  // Lo que más se despegó primero: es lo que vale la pena mirar.
  porCategoria.sort((a, b) => Math.abs(b.variacion) - Math.abs(a.variacion));

  return { gasto, tasaAhorro, porCategoria: porCategoria.filter((c) => Math.abs(c.variacion) > RUIDO) };
}

/** "gastás 15% menos en delivery que tu promedio" */
export function frase(categoria, variacion) {
  const pct = Math.abs(Math.round(variacion * 100));
  const verbo = variacion > 0 ? "más" : "menos";
  return `${pct}% ${verbo} en ${categoria} que tu promedio`;
}
