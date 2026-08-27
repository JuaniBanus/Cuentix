// Cuentas de los objetivos de ahorro. Puras, sin DOM ni red.

import { sumar } from "./format.js";
import { dias, MESES } from "./periodo.js";
import { hoyISO } from "./format.js";

export const PRIORIDADES = ["alta", "media", "baja"];

export const COLORES = ["cat-1", "cat-2", "cat-3", "cat-4", "cat-5", "cat-6"];

export const ICONOS = ["🎯", "✈️", "🏠", "🚗", "🎓", "💻", "🏖️", "🎁", "💍", "🩺", "📚", "🛠️"];

/** Los ahorros imputados a un objetivo, en la moneda del objetivo. */
export function aportesDe(objetivo, ahorros) {
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

/** A este ritmo, cuánto falta. */
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
    lejisimos: meses > 120,
    etiqueta: `${MESES[fin.getMonth()]} ${fin.getFullYear()}`,
  };
}

const ORDEN_PRIORIDAD = { alta: 0, media: 1, baja: 2 };
const ORDEN_ESTADO = { activo: 0, pausado: 1, completado: 2 };

/** Lo que está en curso primero, después lo pausado y al final lo terminado. */
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
