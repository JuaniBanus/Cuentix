// Cliente de Supabase, sesión y consultas.

import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./config.js";

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const PAGINA = 1000;


export const SIN_CONEXION = "No pudimos conectar. Revisá tu conexión.";

/** Un error ya listo para mostrarle a alguien. */
export class ErrorAmable extends Error {
  constructor(mensaje, { esDeConexion = false } = {}) {
    super(mensaje);
    this.name = "ErrorAmable";
    this.esDeConexion = esDeConexion;
  }
}

/** Reconoce un fallo de red mirando lo que devuelve cada navegador, porque no */
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

/** Corre una llamada a Supabase y normaliza las dos formas en que puede fallar: */
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

/** Avisa cada vez que cambia la sesión, la haya cambiado esta pestaña o no. */
export function alCambiarSesion(alCambiar) {
  sb.auth.onAuthStateChange((_evento, sesion) => alCambiar(sesion ?? null));
}

export async function salir() {
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


const PERFILES = "perfiles";

/** El perfil de quien está logueado. null si todavía no tiene. */
export async function traerPerfil(userId) {
  const { data } = await pedir(
    () =>
      sb
        .from(PERFILES)
        .select("user_id, email, estado, rol, debe_cambiar_password, creado_en")
        .eq("user_id", userId)
        .maybeSingle(),
    traducirErrorDePerfil
  );
  return data ?? null;
}

/** Todos los perfiles, para el panel de administración. */
export async function traerUsuarios() {
  const { data } = await pedir(
    () =>
      sb
        .from(PERFILES)
        .select("user_id, email, estado, rol, debe_cambiar_password, creado_en")
        .order("creado_en", { ascending: true }),
    traducirErrorDePerfil
  );
  return data ?? [];
}

/** Activa o pausa una cuenta. */
export async function cambiarEstadoUsuario(userId, estado) {
  await pedir(
    () => sb.rpc("admin_cambiar_estado", { p_user_id: userId, p_estado: estado }),
    traducirErrorDeAdmin
  );
}

/** Cambia la contraseña y baja el flag de cambio obligatorio. */
export async function cambiarPassword(nueva, userId) {
  await pedir(() => sb.auth.updateUser({ password: nueva }), traducirErrorDePassword);

  await pedir(
    () =>
      sb.from(PERFILES).update({ debe_cambiar_password: false }).eq("user_id", userId),
    traducirErrorDePerfil
  );
}

function traducirErrorDePerfil(error) {
  const mensaje = String(error?.message ?? "");
  if (error?.code === "42P01" || /does not exist/i.test(mensaje)) {
    return "Falta crear la tabla de perfiles en Supabase.";
  }
  if (/jwt|expired/i.test(mensaje)) return "La sesión venció. Volvé a entrar.";
  return "No pude leer tu perfil. Probá de nuevo en un momento.";
}

function traducirErrorDeAdmin(error) {
  const mensaje = String(error?.message ?? "");
  if (/superusuario/i.test(mensaje)) return "No tenés permiso para hacer eso.";
  if (/tu propio estado/i.test(mensaje)) return "No podés cambiar tu propio estado.";
  if (/does not exist|42883/i.test(mensaje)) {
    return "Falta correr la migración que crea admin_cambiar_estado.";
  }
  return "No pude cambiar el estado de esa cuenta.";
}

function traducirErrorDePassword(error) {
  const mensaje = String(error?.message ?? "");
  if (/at least|should be at least|weak/i.test(mensaje)) {
    return "La contraseña es muy corta. Poné al menos 8 caracteres.";
  }
  if (/same.*password|different from the old/i.test(mensaje)) {
    return "Tiene que ser distinta de la que estás usando.";
  }
  if (/jwt|expired/i.test(mensaje)) return "La sesión venció. Volvé a entrar.";
  return "No pude cambiar la contraseña. Probá de nuevo.";
}


/** Trae movimientos con filtros opcionales, del más reciente al más viejo. */
export async function traerMovimientos({ desde, hasta, tipo } = {}) {
  const filas = [];

  for (let pagina = 0; ; pagina++) {
    let consulta = sb
      .from("movimientos")
      .select(
        "id, fecha, tipo, monto, moneda, categoria, descripcion, cuenta, objetivo_id, " +
        "clave_item, comercio, cantidad, unidad, precio_unitario"
      )
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
  if (error?.code === "PGRST301" || /jwt|permission/i.test(error?.message ?? "")) {
    return "La sesión venció o la policy de lectura no está creada.";
  }
  return "No pudimos leer tus movimientos. Probá de nuevo en un momento.";
}

/** Los movimientos del período elegido: es lo que miran todas las pantallas. */
export function traerPeriodo({ desde, hasta }) {
  return traerMovimientos({ desde, hasta });
}


/** Las tenencias del usuario, de la compra más reciente a la más vieja. */
export async function traerInversiones() {
  const filas = [];

  for (let pagina = 0; ; pagina++) {
    const consulta = sb
      .from("inversiones")
      .select("id, tipo, ticker, nombre, cantidad, precio_compra, moneda, fecha_compra, sector")
      .order("fecha_compra", { ascending: false })
      .order("created_at", { ascending: false })
      .range(pagina * PAGINA, (pagina + 1) * PAGINA - 1);

    const { data } = await pedir(() => consulta, traducirErrorDeInversiones);

    filas.push(...data);
    if (data.length < PAGINA) {
      return filas.map((f) => ({
        ...f,
        cantidad: Number(f.cantidad),
        precio_compra: Number(f.precio_compra),
      }));
    }
  }
}

function traducirErrorDeInversiones(error) {
  if (error?.code === "PGRST301" || /jwt|permission/i.test(error?.message ?? "")) {
    return "La sesión venció o la policy de lectura no está creada.";
  }
  if (error?.code === "42P01" || /does not exist/i.test(error?.message ?? "")) {
    return "Todavía no está creada la tabla de inversiones.";
  }
  return "No pudimos leer tus inversiones. Probá de nuevo en un momento.";
}


const OBJETIVOS = "objetivos";

/** Los retos del usuario, del más nuevo al más viejo. La web solo LEE: los */
export async function traerRetos() {
  const { data, error } = await sb
    .from("retos")
    .select("id, categoria, tipo, objetivo, ahorro_estimado, moneda, desde, hasta, estado, gastado")
    .order("created_at", { ascending: false })
    .limit(30);
  if (error) throw new Error(traducirErrorDeDatos(error));
  return data ?? [];
}

/** Las TNA de las billeteras virtuales, de mayor a menor. */
export async function traerRendimientos() {
  const { data, error } = await sb
    .from("rendimientos_billeteras")
    .select("nombre, tipo, tna, tope_monto, fecha_actualizacion, fondo")
    .order("tna", { ascending: false })
    .limit(60);
  if (error) {
    console.warn("No pude leer los rendimientos de billeteras:", error.message);
    return [];
  }
  return (data ?? []).map((f) => ({
    ...f,
    tna: Number(f.tna),
    tope_monto: f.tope_monto == null ? null : Number(f.tope_monto),
  }));
}

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

  if (codigo === "PGRST116") {
    return "No encontré ese objetivo. Puede que ya lo hayas borrado.";
  }
  if (codigo === "42501" || /row-level security|policy/i.test(mensaje)) {
    return "No tenés permiso para tocar ese objetivo.";
  }
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
