// Registro total de lo ahorrado: mes a mes, separado por moneda.

function mesDe(iso) {
  return String(iso ?? "").slice(0, 7);
}

/** Orden de visualización: pesos y dólares primero, el resto alfabético. */
const ORDEN = { ARS: 0, USD: 1 };
function comparar(a, b) {
  const oa = ORDEN[a] ?? 2;
  const ob = ORDEN[b] ?? 2;
  return oa - ob || a.localeCompare(b);
}

/**
 * Agrupa los ahorros por mes y por moneda.
 *
 * Devuelve:
 *  - monedas: las monedas que aparecen en el historial, en orden de visualización.
 *  - meses: [{ mes, porMoneda: { ARS: 1234, USD: 56 } }], del más viejo al más nuevo.
 *  - totales: { ARS: 12345, USD: 678 }, el acumulado de todo el historial.
 */
export function registroAhorro(ahorros) {
  const porMes = new Map(); // mes -> Map(moneda -> centavos)
  const totales = new Map(); // moneda -> centavos
  const monedas = new Set();

  for (const m of ahorros ?? []) {
    if (m.tipo !== "ahorro") continue;
    const mes = mesDe(m.fecha);
    const moneda = m.moneda;
    const centavos = Math.round((Number(m.monto) || 0) * 100);
    if (!mes || !moneda || !centavos) continue;

    monedas.add(moneda);
    if (!porMes.has(mes)) porMes.set(mes, new Map());
    const delMes = porMes.get(mes);
    delMes.set(moneda, (delMes.get(moneda) ?? 0) + centavos);
    totales.set(moneda, (totales.get(moneda) ?? 0) + centavos);
  }

  const meses = [...porMes.keys()]
    .sort()
    .reverse()
    .map((mes) => ({
      mes,
      porMoneda: Object.fromEntries(
        [...porMes.get(mes)].map(([moneda, centavos]) => [moneda, centavos / 100])
      ),
    }));

  return {
    monedas: [...monedas].sort(comparar),
    meses,
    totales: Object.fromEntries(
      [...totales].map(([moneda, centavos]) => [moneda, centavos / 100])
    ),
  };
}
