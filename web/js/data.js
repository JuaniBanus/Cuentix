// Cliente de Supabase, sesión y consultas.
//
// Solo lo que toca la red. Las cuentas sobre los movimientos viven en
// cuentas.js, que no depende de nada de acá.

import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./config.js";

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// PostgREST devuelve como máximo 1000 filas por respuesta. Hoy sobra, pero sin
// paginar un total sobre todo el historial se calcularía en silencio sobre las
// primeras 1000 nomás.
const PAGINA = 1000;

// --------------------------------------------------------------------------
// Errores
// --------------------------------------------------------------------------
//
// Ninguna llamada a Supabase sale de este archivo sin pasar por acá. Afuera
// nadie ve un "TypeError: Failed to fetch": ven una frase en castellano y, si
// el problema es la conexión, un aviso con botón de reintentar.

export const SIN_CONEXION = "No pudimos conectar. Revisá tu conexión.";

/** Un error ya listo para mostrarle a alguien. */
export class ErrorAmable extends Error {
  constructor(mensaje, { esDeConexion = false } = {}) {
    super(mensaje);
    this.name = "ErrorAmable";
    this.esDeConexion = esDeConexion;
  }
}

/**
 * Reconoce un fallo de red mirando lo que devuelve cada navegador, porque no
 * hay un tipo común: Chrome tira "Failed to fetch", Safari "Load failed",
 * Firefox "NetworkError...", y supabase-js envuelve los suyos en clases propias
 * con "Retryable" o "Fetch" en el nombre.
 */
function esFalloDeRed(problema) {
  if (!navigator.onLine) return true;
  const nombre = String(problema?.name ?? "");
  const mensaje = String(problema?.message ?? problema ?? "");
  return (
    problema instanceof TypeError ||
    /Retryable|FetchError|AbortError|TimeoutError/i.test(nombre) ||
    /failed to fetch|load failed|networkerror|network request failed|timeout|ECONNRESET/i.test(mensaje)
  );
}

/**
 * Corre una llamada a Supabase y normaliza las dos formas en que puede fallar:
 * tirando una excepción (se cayó la red) o devolviendo {error} (el servidor
 * contestó que no).
 *
 * @param {() => Promise<{data: any, error: any}>} llamada
 * @param {(error: any) => string} traducir  qué decir si el error no es de red
 */
async function pedir(llamada, traducir) {
  if (!navigator.onLine) throw new ErrorAmable(SIN_CONEXION, { esDeConexion: true });

  let respuesta;
  try {
    respuesta = await llamada();
  } catch (problema) {
    if (esFalloDeRed(problema)) throw new ErrorAmable(SIN_CONEXION, { esDeConexion: true });
    throw new ErrorAmable(traducir(problema));
  }

  if (respuesta?.error) {
    if (esFalloDeRed(respuesta.error)) {
      throw new ErrorAmable(SIN_CONEXION, { esDeConexion: true });
    }
    throw new ErrorAmable(traducir(respuesta.error));
  }

  return respuesta;
}

export async function sesionActual() {
  // getSession lee del almacenamiento local, sin red: sirve para entrar a la
  // app estando offline y ver el aviso adentro en vez del login.
  const { data } = await sb.auth.getSession();
  return data.session;
}

/** Devuelve la sesión: de ahí sale el email que muestra la pantalla Usuario. */
export async function entrar(email, password) {
  const { data } = await pedir(
    () => sb.auth.signInWithPassword({ email, password }),
    traducirErrorDeLogin
  );
  return data.session;
}

export async function salir() {
  // Cerrar sesión tiene que funcionar sin internet: el token se borra del
  // navegador igual, aunque no se pueda avisarle al servidor.
  try {
    await sb.auth.signOut();
  } catch {
    await sb.auth.signOut({ scope: "local" }).catch(() => {});
  }
}

function traducirErrorDeLogin(error) {
  const mensaje = String(error?.message ?? error);
  if (/invalid login credentials/i.test(mensaje)) return "Email o contraseña incorrectos.";
  if (/email not confirmed/i.test(mensaje)) return "Falta confirmar el email de la cuenta.";
  if (/too many requests|rate limit/i.test(mensaje)) {
    return "Demasiados intentos seguidos. Probá de nuevo en un rato.";
  }
  return "No pudimos entrar. Probá de nuevo en un momento.";
}

/** Trae movimientos con filtros opcionales, del más reciente al más viejo. */
export async function traerMovimientos({ desde, hasta, tipo } = {}) {
  const filas = [];

  for (let pagina = 0; ; pagina++) {
    let consulta = sb
      .from("movimientos")
      .select("id, fecha, tipo, monto, moneda, categoria, descripcion, cuenta, objetivo_id")
      .order("fecha", { ascending: false })
      .order("id", { ascending: false })
      .range(pagina * PAGINA, (pagina + 1) * PAGINA - 1);

    if (desde) consulta = consulta.gte("fecha", desde);
    if (hasta) consulta = consulta.lte("fecha", hasta);
    if (tipo) consulta = consulta.eq("tipo", tipo);

    const { data } = await pedir(() => consulta, traducirErrorDeDatos);

    filas.push(...data);
    if (data.length < PAGINA) return filas;
  }
}

function traducirErrorDeDatos(error) {
  // Con RLS activo y sin sesión válida, PostgREST no dice "no tenés permiso":
  // devuelve una lista vacía o un 401. Este mensaje ahorra media hora de
  // buscar el problema en el lugar equivocado.
  if (error?.code === "PGRST301" || /jwt|permission/i.test(error?.message ?? "")) {
    return "La sesión venció o la policy de lectura no está creada.";
  }
  return "No pudimos leer tus movimientos. Probá de nuevo en un momento.";
}

/** Los movimientos del período elegido: es lo que miran todas las pantallas. */
export function traerPeriodo({ desde, hasta }) {
  return traerMovimientos({ desde, hasta });
}

// --------------------------------------------------------------------------
// Objetivos de ahorro
// --------------------------------------------------------------------------
//
// La única tabla donde la web escribe. Los movimientos siguen siendo de solo
// lectura: los carga el bot.
//
// Nada de esto manda `user_id`. Lo pone el default `auth.uid()` de la tabla, y
// la policy de INSERT rechazaría cualquier otro valor. El JWT del usuario lo
// adjunta supabase-js solo, con la sesión que ya tiene guardada: por eso las
// policies ven al usuario correcto sin que haya que pasarles nada.
//
// Tampoco hace falta filtrar por usuario al leer ni al borrar: con RLS activa,
// las filas ajenas directamente no existen para esta sesión.

const OBJETIVOS = "objetivos";

export async function traerObjetivos() {
  const { data } = await pedir(
    () => sb.from(OBJETIVOS).select("*").order("created_at", { ascending: false }),
    traducirErrorDeObjetivos
  );
  return data ?? [];
}

export async function crearObjetivo(datos) {
  const { data } = await pedir(
    () => sb.from(OBJETIVOS).insert(datos).select().single(),
    traducirErrorDeObjetivos
  );
  return data;
}

export async function editarObjetivo(id, datos) {
  const { data } = await pedir(
    () => sb.from(OBJETIVOS).update(datos).eq("id", id).select().single(),
    traducirErrorDeObjetivos
  );
  return data;
}

export async function borrarObjetivo(id) {
  await pedir(() => sb.from(OBJETIVOS).delete().eq("id", id), traducirErrorDeObjetivos);
}

function traducirErrorDeObjetivos(error) {
  const codigo = error?.code ?? "";
  const mensaje = String(error?.message ?? "");

  // PGRST116: se pidió una fila y volvieron cero. Con RLS eso es casi siempre
  // "no es tuya" o "ya no está", no un problema de la app.
  if (codigo === "PGRST116") {
    return "No encontré ese objetivo. Puede que ya lo hayas borrado.";
  }
  if (codigo === "42501" || /row-level security|policy/i.test(mensaje)) {
    return "No tenés permiso para tocar ese objetivo.";
  }
  // 23514 = violación de un CHECK; 23502 = un NOT NULL sin valor.
  if (codigo === "23514" || codigo === "23502") {
    return "Hay un dato fuera de lo permitido. Revisá el monto y la fecha.";
  }
  if (codigo === "42P01" || /relation .* does not exist/i.test(mensaje)) {
    return "Falta crear la tabla de objetivos en Supabase.";
  }
  if (/jwt|expired/i.test(mensaje)) {
    return "La sesión venció. Volvé a entrar.";
  }
  return "No pude guardar el objetivo. Probá de nuevo en un momento.";
}
