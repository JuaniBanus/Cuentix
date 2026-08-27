// Narrativa mensual: pedir el resumen, guardarlo y leer los anteriores.

import { BACKEND_URL } from "./config.js";
import { comparar } from "./comparacion.js";
import { sb } from "./data.js";
import { detectar, totalMensual } from "./recurrentes.js";
import { calcular as calcularTermometro } from "./termometro.js";

const TABLA = "narrativas";

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

export function nombreDelMes(mes) {
  const [a, m] = mes.split("-");
  return `${MESES[Number(m) - 1]} de ${a}`;
}

/** El mes anterior al actual: el último que está cerrado. */
export function ultimoMesCerrado(hoy = new Date()) {
  const d = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Las narrativas ya guardadas, de la más nueva a la más vieja. */
export async function traerNarrativas() {
  const { data, error } = await sb
    .from(TABLA)
    .select("mes, texto, moneda, created_at")
    .order("mes", { ascending: false })
    .limit(24);
  if (error) throw new Error("No pude leer los resúmenes guardados.");
  return data ?? [];
}

/** Arma los agregados de un mes. Todo número, nada de texto del usuario. */
export function agregados(historial, objetivos, mes, moneda) {
  const delMes = historial.filter((m) => m.moneda === moneda && (m.fecha ?? "").startsWith(mes));
  const suma = (tipo) =>
    delMes.filter((m) => m.tipo === tipo).reduce((t, m) => t + (Number(m.monto) || 0), 0);

  const gastado = suma("gasto");
  const ingresado = suma("ingreso");
  const ahorrado = suma("ahorro");

  const comp = comparar(historial, delMes, mes, moneda);

  const porCategoria = new Map();
  for (const m of delMes) {
    if (m.tipo !== "gasto") continue;
    const c = (m.categoria || "otros").trim();
    porCategoria.set(c, (porCategoria.get(c) ?? 0) + (Number(m.monto) || 0));
  }
  const variacionDe = new Map(comp.porCategoria.map((c) => [c.categoria, c.variacion]));

  const termo = calcularTermometro(historial.filter((m) => m.moneda === moneda));
  const recurrentes = detectar(historial, moneda, `${mes}-28`);

  return {
    mes: nombreDelMes(mes),
    moneda,
    total_gastado: gastado.toFixed(2),
    total_ingresado: ingresado > 0 ? ingresado.toFixed(2) : null,
    total_ahorrado: ahorrado > 0 ? ahorrado.toFixed(2) : null,
    gasto_promedio_meses_previos: comp.gasto ? comp.gasto.promedio.toFixed(2) : null,
    meses_de_historia: comp.gasto ? comp.gasto.meses : 0,
    tasa_ahorro_pct: ingresado > 0 ? (ahorrado / ingresado) * 100 : null,
    tasa_ahorro_promedio_pct: comp.tasaAhorro ? comp.tasaAhorro.promedio * 100 : null,
    categorias: [...porCategoria.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([nombre, total]) => ({
        nombre,
        total: total.toFixed(2),
        variacion_vs_promedio_pct: variacionDe.has(nombre)
          ? variacionDe.get(nombre) * 100
          : null,
      })),
    objetivos: (objetivos ?? []).slice(0, 6).map((o) => ({
      nombre: o.nombre,
      porcentaje: Math.min(Math.round((o.aportado ?? 0) / (Number(o.monto_objetivo) || 1) * 100), 999),
      aportado_en_el_mes: null,
    })),
    inflacion_personal_pct: termo.tem !== null ? termo.tem * 100 : null,
    recurrentes_total: recurrentes.length ? totalMensual(recurrentes).toFixed(2) : null,
    recurrentes_cantidad: recurrentes.length,
  };
}

/** Pide el texto al backend y lo guarda. Devuelve la fila creada. */
export async function generarYGuardar(datos, mes) {
  const { data: sesion } = await sb.auth.getSession();
  const token = sesion?.session?.access_token;
  if (!token) throw new Error("La sesión venció. Entrá de nuevo.");

  const respuesta = await fetch(`${BACKEND_URL}/narrativa`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(datos),
  });

  if (!respuesta.ok) {
    throw new Error(
      respuesta.status === 401
        ? "La sesión venció. Entrá de nuevo."
        : "No pude escribir el resumen del mes. Probá en un rato."
    );
  }

  const { texto } = await respuesta.json();
  if (!texto) throw new Error("El resumen salió vacío.");

  const { data, error } = await sb
    .from(TABLA)
    .upsert({ mes, texto, moneda: datos.moneda }, { onConflict: "user_id,mes" })
    .select()
    .single();

  if (error) throw new Error("Escribí el resumen pero no pude guardarlo.");
  return data;
}
