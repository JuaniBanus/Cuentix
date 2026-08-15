// Inflación personal: cuánto subió la canasta propia.
//
// Es el espejo en JavaScript de app/inflacion.py. Se duplica el cálculo a
// propósito y no se expone un endpoint: la web ya lee los movimientos directo
// de Supabase, así que pedirle el número al bot sumaría una llamada de red,
// una dependencia con Render dormido y un motivo más para que la pantalla
// quede en blanco. El precio de la duplicación es mantener dos versiones de la
// misma regla; está acotado porque la regla es corta y no cambia seguido.
//
// LO QUE ENTRA AL ÍNDICE
// Solo lo comparable: servicios, donde el total ES el precio, y compras con
// precio unitario capturado. El súper y la comida quedan afuera —su total
// mezcla precio con cantidad— y se muestran aparte como gasto.
//
// Un ítem necesita dos compras en MESES distintos. Dos del mismo día no dicen
// nada sobre la evolución de un precio.

// Categorías donde el total del movimiento es el precio del servicio.
const CATEGORIAS_SERVICIO = new Set([
  "servicios", "alquiler", "expensas", "internet", "telefono", "celular",
  "luz", "gas", "agua", "cable", "streaming", "gimnasio", "prepaga",
  "obra social", "seguro", "impuestos", "educacion", "colegio", "cochera",
]);

const MESES_MINIMOS = 0.8;
// Más que esto casi siempre es otro ítem mal agrupado, no un aumento.
const VARIACION_ABSURDA = 10;

function sinTildes(texto) {
  return String(texto ?? "").toLowerCase().normalize("NFD").replace(/\p{Mn}/gu, "");
}

/** ¿El total de este gasto es un precio comparable? */
export function esComparable(categoria, tienePrecioUnitario) {
  return tienePrecioUnitario || CATEGORIAS_SERVICIO.has(sinTildes(categoria).trim());
}

function precioDe(fila) {
  const unitario = Number(fila.precio_unitario);
  if (Number.isFinite(unitario) && unitario > 0) return { precio: unitario, unitario: true };
  const monto = Number(fila.monto);
  return Number.isFinite(monto) && monto > 0 ? { precio: monto, unitario: false } : null;
}

/**
 * Calcula el termómetro a partir de los gastos con clave_item.
 *
 * @returns {{tem: number|null, items: Array, descartados: Array, desde, hasta}}
 */
export function calcular(movimientos) {
  const porItem = new Map();

  for (const fila of movimientos) {
    if (fila.tipo !== "gasto") continue;
    const clave = (fila.clave_item ?? "").trim();
    if (!clave) continue;

    const precio = precioDe(fila);
    if (!precio) continue;

    if (!porItem.has(clave)) porItem.set(clave, { obs: [], categoria: fila.categoria ?? "", unitario: false });
    const item = porItem.get(clave);
    item.obs.push({ fecha: fila.fecha, ...precio, gastado: Number(fila.monto) || 0 });
    item.unitario = item.unitario || precio.unitario;
  }

  const items = [];
  const descartados = [];

  for (const [clave, { obs, categoria, unitario }] of porItem) {
    if (obs.length < 2) continue;
    obs.sort((a, b) => a.fecha.localeCompare(b.fecha));

    const meses = new Set(obs.map((o) => o.fecha.slice(0, 7)));
    if (meses.size < 2) {
      descartados.push([clave, "todas las compras en el mismo mes"]);
      continue;
    }

    if (!esComparable(categoria, unitario)) {
      descartados.push([clave, "el total mezcla precio y cantidad; falta el precio por unidad"]);
      continue;
    }

    const primera = obs[0];
    const ultima = obs[obs.length - 1];
    const dias = (new Date(ultima.fecha) - new Date(primera.fecha)) / 86400000;
    const cantidadMeses = dias / 30.44;

    if (cantidadMeses < MESES_MINIMOS || primera.precio <= 0) {
      descartados.push([clave, "muy poco tiempo entre compras"]);
      continue;
    }

    const variacion = ultima.precio / primera.precio - 1;
    if (Math.abs(variacion) > VARIACION_ABSURDA) {
      descartados.push([clave, `variación de ${Math.round(variacion * 100)}%: parece otro ítem mezclado`]);
      continue;
    }

    items.push({
      clave,
      unitario,
      observaciones: obs.length,
      primera: primera.fecha,
      ultima: ultima.fecha,
      precioInicial: primera.precio,
      precioFinal: ultima.precio,
      variacion,
      // Geométrica: un 20% en cuatro meses es 4,66% mensual, no 5%.
      tem: (ultima.precio / primera.precio) ** (1 / cantidadMeses) - 1,
      // El ponderador: cuánto pesa este ítem en el gasto del período.
      peso: obs.reduce((t, o) => t + o.gastado, 0),
    });
  }

  items.sort((a, b) => b.variacion - a.variacion);

  let tem = null;
  if (items.length) {
    const pesoTotal = items.reduce((t, i) => t + i.peso, 0);
    // Ponderado por gasto: que suba 10% el alquiler no es lo mismo que suba
    // 10% el café, aunque los dos sean "un ítem que aumentó 10%".
    if (pesoTotal > 0) tem = items.reduce((t, i) => t + i.tem * i.peso, 0) / pesoTotal;
  }

  return {
    tem,
    items,
    descartados,
    desde: items.length ? items.reduce((m, i) => (i.primera < m ? i.primera : m), items[0].primera) : null,
    hasta: items.length ? items.reduce((m, i) => (i.ultima > m ? i.ultima : m), items[0].ultima) : null,
  };
}

/** Gasto mensual por categoría variable: es gasto, NO precio. Va aparte. */
export function gastoPorCategoria(movimientos) {
  const porCategoriaMes = new Map();

  for (const fila of movimientos) {
    if (fila.tipo !== "gasto") continue;
    const categoria = (fila.categoria ?? "otros").trim();
    if (esComparable(categoria, Number(fila.precio_unitario) > 0)) continue;

    const mes = (fila.fecha ?? "").slice(0, 7);
    if (!mes) continue;
    if (!porCategoriaMes.has(categoria)) porCategoriaMes.set(categoria, new Map());
    const meses = porCategoriaMes.get(categoria);
    meses.set(mes, (meses.get(mes) ?? 0) + (Number(fila.monto) || 0));
  }

  const salida = [];
  for (const [categoria, meses] of porCategoriaMes) {
    if (meses.size < 2) continue;
    const ordenados = [...meses.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    const [mesInicial, montoInicial] = ordenados[0];
    const [mesFinal, montoFinal] = ordenados[ordenados.length - 1];
    if (montoInicial <= 0) continue;
    salida.push({
      categoria, mesInicial, mesFinal, montoInicial, montoFinal,
      variacion: montoFinal / montoInicial - 1,
    });
  }
  return salida.sort((a, b) => b.variacion - a.variacion);
}
