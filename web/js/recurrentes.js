// Detección de gastos recurrentes y suscripciones.
//
// QUÉ CUENTA COMO RECURRENTE
// Tres condiciones juntas, y las tres hacen falta:
//
//   1. Al menos 3 cargos del mismo ítem. Con 2 no hay periodicidad, hay una
//      coincidencia.
//   2. Espaciados de forma regular. Se mide la MEDIANA de los días entre
//      cargos y se exige que los intervalos no se desvíen mucho de ella: un
//      Netflix cae cada 30 ± 3 días, un almuerzo cae cuando cae.
//   3. Monto estable. Se compara cada cargo contra la mediana; si varían
//      demasiado, es un rubro que se repite, no una suscripción.
//
// La tercera es la que separa "gasto recurrente" de "gasto frecuente". El
// súper también aparece todos los meses, pero por montos distintos: eso es un
// hábito, no un débito automático.
//
// LO QUE NO HACE
// No cancela nada ni recomienda cancelar. Muestra lo que se está pagando y
// hace cuánto, que es información que la gente no tiene a mano. Qué hacer con
// eso es del usuario.

// Con menos de 3 no hay periodicidad que medir.
const CARGOS_MINIMOS = 3;
// Cuánto puede desviarse un intervalo de la mediana sin dejar de ser regular.
const TOLERANCIA_DIAS = 0.35;
// Cuánto puede variar el monto respecto de la mediana.
const TOLERANCIA_MONTO = 0.25;
// Períodos que se reconocen, en días.
const PERIODOS = [
  { nombre: "semanal", dias: 7, porMes: 4.33 },
  { nombre: "quincenal", dias: 15, porMes: 2 },
  { nombre: "mensual", dias: 30.44, porMes: 1 },
  { nombre: "bimestral", dias: 61, porMes: 0.5 },
  { nombre: "trimestral", dias: 91, porMes: 0.33 },
  { nombre: "anual", dias: 365, porMes: 1 / 12 },
];

function mediana(valores) {
  if (!valores.length) return 0;
  const o = [...valores].sort((a, b) => a - b);
  const m = Math.floor(o.length / 2);
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
}

function periodoDe(diasMediana) {
  let mejor = null;
  let distancia = Infinity;
  for (const p of PERIODOS) {
    const d = Math.abs(diasMediana - p.dias) / p.dias;
    if (d < distancia) [mejor, distancia] = [p, d];
  }
  // Si no se parece a ningún período conocido, no es una suscripción.
  return distancia <= TOLERANCIA_DIAS ? mejor : null;
}

/** Clave de agrupación: la del termómetro si está, si no la descripción. */
function claveDe(m) {
  return (m.clave_item || m.comercio || m.descripcion || m.categoria || "").trim().toLowerCase();
}

/**
 * @param {Array} movimientos gastos, TODA la historia
 * @param {string} moneda
 * @param {string} hoyISO para calcular "el próximo cae el…"
 * @returns {Array} recurrentes, del que más pesa al que menos
 */
export function detectar(movimientos, moneda, hoyISO) {
  const porItem = new Map();

  for (const m of movimientos ?? []) {
    if (m.tipo !== "gasto" || m.moneda !== moneda) continue;
    const clave = claveDe(m);
    if (!clave) continue;
    const monto = Number(m.monto);
    if (!Number.isFinite(monto) || monto <= 0) continue;
    if (!porItem.has(clave)) porItem.set(clave, []);
    porItem.get(clave).push({ fecha: m.fecha, monto, categoria: m.categoria ?? "" });
  }

  const hoy = new Date(hoyISO ?? new Date().toISOString().slice(0, 10));
  const salida = [];

  for (const [clave, cargos] of porItem) {
    if (cargos.length < CARGOS_MINIMOS) continue;
    cargos.sort((a, b) => a.fecha.localeCompare(b.fecha));

    const intervalos = [];
    for (let i = 1; i < cargos.length; i++) {
      const dias = (new Date(cargos[i].fecha) - new Date(cargos[i - 1].fecha)) / 86400000;
      if (dias > 0) intervalos.push(dias);
    }
    if (intervalos.length < CARGOS_MINIMOS - 1) continue;

    const diasMediana = mediana(intervalos);
    if (diasMediana <= 0) continue;

    // Regularidad: ningún intervalo puede despegarse mucho de la mediana.
    const regular = intervalos.every(
      (d) => Math.abs(d - diasMediana) / diasMediana <= TOLERANCIA_DIAS
    );
    if (!regular) continue;

    const periodo = periodoDe(diasMediana);
    if (!periodo) continue;

    const montos = cargos.map((c) => c.monto);
    const montoTipico = mediana(montos);
    if (montoTipico <= 0) continue;

    const estable = montos.every(
      (x) => Math.abs(x - montoTipico) / montoTipico <= TOLERANCIA_MONTO
    );
    if (!estable) continue;

    const ultimo = cargos[cargos.length - 1];
    const diasDesdeUltimo = Math.round((hoy - new Date(ultimo.fecha)) / 86400000);

    salida.push({
      clave,
      categoria: ultimo.categoria,
      cargos: cargos.length,
      periodo: periodo.nombre,
      montoTipico,
      // Lo que representa por mes, para poder sumarlos entre sí.
      porMes: montoTipico * periodo.porMes,
      primero: cargos[0].fecha,
      ultimo: ultimo.fecha,
      diasDesdeUltimo,
      totalPagado: montos.reduce((t, x) => t + x, 0),
      // Se pasó bastante de su período: puede haberse dado de baja, o puede
      // que el cargo esté por venir. Se marca para revisar, no se concluye.
      vencido: diasDesdeUltimo > periodo.dias * (1 + TOLERANCIA_DIAS * 2),
      // Viene cobrándose hace rato y sigue: candidato a "¿lo seguís usando?".
      mesesActivo: Math.round(
        (new Date(ultimo.fecha) - new Date(cargos[0].fecha)) / 86400000 / 30.44
      ),
    });
  }

  return salida.sort((a, b) => b.porMes - a.porMes);
}

/** Lo que representan todos juntos por mes. */
export function totalMensual(recurrentes) {
  return (recurrentes ?? []).reduce((t, r) => t + r.porMes, 0);
}
