// Cuentas de los objetivos de ahorro. Puras, sin DOM ni red.

import { sumar } from "./format.js";
import { dias, MESES } from "./periodo.js";
import { hoyISO } from "./format.js";

export const PRIORIDADES = ["alta", "media", "baja"];

// Los colores se guardan como nombre de token y no como hex: así el objetivo
// se ve bien en tema claro y en oscuro. Un #12a5bd fijo quedaría lavado sobre
// blanco.
export const COLORES = ["cat-1", "cat-2", "cat-3", "cat-4", "cat-5", "cat-6"];

export const ICONOS = ["🎯", "✈️", "🏠", "🚗", "🎓", "💻", "🏖️", "🎁", "💍", "🩺", "📚", "🛠️"];

/** Los ahorros imputados a un objetivo, en la moneda del objetivo. */
export function aportesDe(objetivo, ahorros) {
  // El filtro por moneda no es un detalle: un ahorro en dólares imputado a un
  // objetivo en pesos sumaría 400 sobre una meta de 500.000.
  return ahorros.filter(
    (m) => m.tipo === "ahorro" && m.objetivo_id === objetivo.id && m.moneda === objetivo.moneda
  );
}

export function progresoDe(objetivo, ahorros) {
  const aportes = aportesDe(objetivo, ahorros);
  const aportado = sumar(aportes);
  const meta = Number(objetivo.monto_objetivo) || 0;
  const porcentaje = meta > 0 ? (aportado / meta) * 100 : 0;

  return {
    aportes,
    aportado,
    meta,
    restante: Math.max(meta - aportado, 0),
    // La barra se corta en 100; el número de al lado puede decir 130%, que es
    // información real: pasaste la meta.
    porcentaje: Math.min(porcentaje, 100),
    porcentajeReal: porcentaje,
    completado: meta > 0 && aportado >= meta,
  };
}

/** "activo" | "pausado" | "completado". El completado se calcula, no se guarda. */
export function estadoDe(objetivo, progreso) {
  if (progreso.completado) return "completado";
  return objetivo.estado === "pausado" ? "pausado" : "activo";
}

/**
 * A este ritmo, cuánto falta.
 *
 * El ritmo sale de dividir lo aportado por el tiempo que llevás aportando, no
 * por la cantidad de aportes: dos depósitos en un año y dos en una semana no
 * son el mismo ritmo.
 *
 * El piso de 30 días evita el absurdo de arrancar: si tu único aporte fue hoy,
 * dividir por medio día daría un ritmo de millones por mes y una proyección de
 * "lo terminás mañana".
 */
export function proyeccion(progreso, hoy = new Date()) {
  if (progreso.completado || !progreso.aportes.length) return null;

  const primero = progreso.aportes.reduce((a, m) => (m.fecha < a ? m.fecha : a), progreso.aportes[0].fecha);
  const transcurridos = Math.max(dias({ desde: primero, hasta: hoyISO(hoy) }), 30);
  const ritmo = progreso.aportado / (transcurridos / 30.44);
  if (ritmo <= 0) return null;

  const meses = Math.ceil(progreso.restante / ritmo);
  const fin = new Date(hoy.getFullYear(), hoy.getMonth() + meses, 1);

  return {
    ritmo,
    meses,
    // Más allá de diez años la cuenta es correcta pero no significa nada.
    lejisimos: meses > 120,
    etiqueta: `${MESES[fin.getMonth()]} ${fin.getFullYear()}`,
  };
}

const ORDEN_PRIORIDAD = { alta: 0, media: 1, baja: 2 };
const ORDEN_ESTADO = { activo: 0, pausado: 1, completado: 2 };

/**
 * Lo que está en curso primero, después lo pausado y al final lo terminado.
 * Dentro de cada grupo, por prioridad y después por la fecha más cercana.
 */
export function ordenar(objetivos, ahorros) {
  return [...objetivos]
    .map((objetivo) => {
      const progreso = progresoDe(objetivo, ahorros);
      return { objetivo, progreso, estado: estadoDe(objetivo, progreso) };
    })
    .sort((a, b) =>
      ORDEN_ESTADO[a.estado] - ORDEN_ESTADO[b.estado] ||
      ORDEN_PRIORIDAD[a.objetivo.prioridad] - ORDEN_PRIORIDAD[b.objetivo.prioridad] ||
      (a.objetivo.fecha_estimada ?? "9999").localeCompare(b.objetivo.fecha_estimada ?? "9999") ||
      a.objetivo.nombre.localeCompare(b.objetivo.nombre, "es")
    );
}

/** "2027-03-15" -> "marzo 2027", que es la precisión que tiene una meta. */
export function mesYAnio(iso) {
  if (!iso) return "";
  const [anio, mes] = iso.split("-").map(Number);
  return `${MESES[mes - 1]} ${anio}`;
}
