// Cliente de Supabase, sesión y consultas.
//
// Las cuentas se hacen en JavaScript y no con agregaciones en SQL, igual que el
// bot las hace en Python: a escala de finanzas personales el costo es nulo y
// evita depender de las funciones de agregación de PostgREST.

import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./config.js";
import { inicioDeMes, sumar } from "./format.js";

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// PostgREST devuelve como máximo 1000 filas por respuesta. Hoy sobra, pero sin
// paginar un total sobre todo el historial se calcularía en silencio sobre las
// primeras 1000 nomás.
const PAGINA = 1000;

export async function sesionActual() {
  const { data } = await sb.auth.getSession();
  return data.session;
}

export async function entrar(email, password) {
  const { error } = await sb.auth.signInWithPassword({ email, password });
  if (error) throw new Error(traducirError(error.message));
}

export async function salir() {
  await sb.auth.signOut();
}

function traducirError(mensaje) {
  if (/invalid login credentials/i.test(mensaje)) return "Email o contraseña incorrectos.";
  if (/email not confirmed/i.test(mensaje)) return "Falta confirmar el email de la cuenta.";
  if (/failed to fetch|network/i.test(mensaje)) return "No pude conectarme. ¿Hay internet?";
  return mensaje;
}

/** Trae movimientos con filtros opcionales, del más reciente al más viejo. */
export async function traerMovimientos({ desde, hasta, tipo } = {}) {
  const filas = [];

  for (let pagina = 0; ; pagina++) {
    let consulta = sb
      .from("movimientos")
      .select("id, fecha, tipo, monto, moneda, categoria, descripcion")
      .order("fecha", { ascending: false })
      .order("id", { ascending: false })
      .range(pagina * PAGINA, (pagina + 1) * PAGINA - 1);

    if (desde) consulta = consulta.gte("fecha", desde);
    if (hasta) consulta = consulta.lte("fecha", hasta);
    if (tipo) consulta = consulta.eq("tipo", tipo);

    const { data, error } = await consulta;
    if (error) throw new Error(traducirErrorDeDatos(error));

    filas.push(...data);
    if (data.length < PAGINA) return filas;
  }
}

function traducirErrorDeDatos(error) {
  // Con RLS activo y sin sesión válida, PostgREST no dice "no tenés permiso":
  // devuelve una lista vacía o un 401. Este mensaje ahorra media hora de
  // buscar el problema en el lugar equivocado.
  if (error.code === "PGRST301" || /jwt|permission/i.test(error.message ?? "")) {
    return "La sesión venció o la policy de lectura no está creada.";
  }
  return error.message ?? "No pude leer los movimientos.";
}

/** Agrupa por moneda: { ARS: [...], USD: [...] }. */
export function porMoneda(movimientos) {
  const grupos = {};
  for (const m of movimientos) (grupos[m.moneda] ??= []).push(m);
  return grupos;
}

/** Total por tipo dentro de una moneda. */
export function totalPorTipo(movimientos, tipo) {
  return sumar(movimientos.filter((m) => m.tipo === tipo));
}

/** [{categoria, total, porcentaje}] de mayor a menor, para un tipo y moneda. */
export function totalesPorCategoria(movimientos, tipo) {
  const delTipo = movimientos.filter((m) => m.tipo === tipo);
  const total = sumar(delTipo);

  const acumulado = new Map();
  for (const m of delTipo) {
    const centavos = Math.round(Number(m.monto) * 100);
    acumulado.set(m.categoria, (acumulado.get(m.categoria) ?? 0) + centavos);
  }

  return [...acumulado.entries()]
    .map(([categoria, centavos]) => ({
      categoria,
      total: centavos / 100,
      porcentaje: total ? (centavos / 100 / total) * 100 : 0,
    }))
    .sort((a, b) => b.total - a.total);
}

/** Los movimientos del mes en curso, que es lo que mira casi toda la app. */
export function traerMesActual() {
  return traerMovimientos({ desde: inicioDeMes() });
}
