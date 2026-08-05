// Arranque: resuelve la sesión, trae los datos y le pasa el control al router.

import { enfocarLogin, montarLogin } from "./auth.js";
import {
  borrarObjetivo as borrarEnLaBase,
  crearObjetivo,
  editarObjetivo,
  salir,
  sesionActual,
  traerMovimientos,
  traerObjetivos,
  traerPeriodo,
} from "./data.js";
import { traerCotizacion } from "./dolar.js";
import { estado, reiniciarEstado } from "./estado.js";
import { alternarDolares, alternarOcultos, fijarCotizacion, montosOcultos } from "./format.js";
import { anterior, mesActual } from "./periodo.js";
import { registrarServiceWorker } from "./pwa.js";
import { montarNavegacion, pintar } from "./router.js";
import { fijarPeriodo, montarSelectorPeriodo } from "./selectorPeriodo.js";
import { seguirAlSistema } from "./tema.js";

const vistas = {
  carga: document.querySelector("#vista-carga"),
  login: document.querySelector("#vista-login"),
  app: document.querySelector("#vista-app"),
};

/** Una sola vista visible a la vez: login y app nunca conviven en pantalla. */
function mostrar(cual) {
  for (const [nombre, nodo] of Object.entries(vistas)) nodo.hidden = nombre !== cual;
}

const contenido = document.querySelector("#contenido");

// --------------------------------------------------------------------------
// Sesión
// --------------------------------------------------------------------------

async function arrancar() {
  // El tema ya lo aplicó el script de index.html antes del primer pintado; acá
  // solo queda escuchar al sistema por si cambia con la app abierta.
  seguirAlSistema();
  registrarServiceWorker();

  montarNavegacion({
    nav: document.querySelector("#tabs"),
    contenido,
    acciones: { onSalir: cerrarSesion, recargar: cargarDatos, guardarObjetivo, borrarObjetivo },
  });
  montarSelectorPeriodo({
    periodoInicial: estado.periodo,
    onCambio: (periodo) => {
      estado.periodo = periodo;
      estado.categoriaAbierta = null;
      cargarDatos();
    },
  });
  montarLogin(abrirApp);

  let sesion = null;
  try {
    sesion = await sesionActual();
  } catch {
    // Si la sesión guardada no se puede validar (token vencido, sin red),
    // se pide login de nuevo: es preferible a quedarse en la carga para siempre.
  }

  if (sesion) await abrirApp(sesion);
  else mostrarLogin();
}

function mostrarLogin() {
  mostrar("login");
  enfocarLogin();
}

async function abrirApp(sesion) {
  estado.email = sesion?.user?.email ?? "";
  mostrar("app");
  await cargarDatos();
  cargarCotizacion(); // sin await: llega cuando llega
}

async function cerrarSesion() {
  await salir();
  reiniciarEstado();
  fijarPeriodo(mesActual());
  mostrarLogin();
}

// --------------------------------------------------------------------------
// Datos
// --------------------------------------------------------------------------

async function cargarDatos() {
  contenido.innerHTML = `<p class="cargando">Cargando…</p>`;
  try {
    // Las dos consultas salen juntas: la comparación contra el período anterior
    // la necesita Gastos, y pedirla recién al entrar a esa pantalla dejaría un
    // hueco de carga cada vez que se toca la tab.
    const [actuales, previos, ahorros, objetivos] = await Promise.all([
      traerPeriodo(estado.periodo),
      traerPeriodo(anterior(estado.periodo)),
      // Sin acotar por fecha: la evolución del ahorro se lee sobre la historia
      // entera, no sobre el mes elegido.
      traerMovimientos({ tipo: "ahorro" }),
      traerObjetivos(),
    ]);

    estado.movimientos = actuales;
    estado.movimientosPrevios = previos;
    estado.historialAhorros = ahorros;
    estado.objetivos = objetivos;
    estado.error = null;

    // Las monedas salen de los datos, no de una lista fija: si nunca cargaste
    // un gasto en dólares, el selector no aparece.
    const presentes = [...new Set(estado.movimientos.map((m) => m.moneda))];
    estado.monedas = presentes.length ? presentes.sort() : ["ARS"];
    if (!estado.monedas.includes(estado.moneda)) estado.moneda = estado.monedas[0];
  } catch (problema) {
    // El error se guarda en el estado en vez de escribirse acá: así sigue a la
    // vista aunque se cambie de pestaña, y Usuario funciona igual.
    estado.error = problema;
    estado.movimientos = [];
    estado.movimientosPrevios = [];
    estado.historialAhorros = [];
    estado.objetivos = [];
  }
  pintar();
}

// --------------------------------------------------------------------------
// Objetivos: la única parte de la app que escribe
// --------------------------------------------------------------------------

/**
 * Lo que se puede rechazar sin molestar al servidor. Los checks de la tabla
 * son la garantía real; esto es para no hacer ir y volver un pedido que ya
 * sabemos que va a fallar, y para poder decir qué campo está mal.
 */
function revisar(datos) {
  if (!datos.nombre) return "Poné un nombre.";

  const monto = Number(datos.monto_objetivo);
  if (!Number.isFinite(monto) || monto <= 0) return "El monto tiene que ser mayor que cero.";
  if (monto > 99_999_999_999.99) return "Ese monto no entra en la base.";

  return null;
}

async function guardarObjetivo(datos) {
  const problema = revisar(datos);
  if (problema) {
    estado.errorObjetivo = problema;
    pintar();
    return;
  }

  estado.guardando = true;
  estado.errorObjetivo = null;
  pintar();

  try {
    // El id sale de la vista: "nuevo" es alta, cualquier otra cosa es edición.
    if (estado.vistaObjetivo === "nuevo") await crearObjetivo(datos);
    else await editarObjetivo(estado.vistaObjetivo, datos);

    // Se relee en vez de parchear la lista en memoria: así se ven los defaults
    // que puso Postgres y no queda una copia que discrepa de la base.
    estado.objetivos = await traerObjetivos();
    estado.vistaObjetivo = null;
  } catch (problema) {
    estado.errorObjetivo = problema.message;
  } finally {
    estado.guardando = false;
    pintar();
  }
}

async function borrarObjetivo(id) {
  estado.guardando = true;
  pintar();

  try {
    await borrarEnLaBase(id);
    estado.objetivos = await traerObjetivos();
    estado.vistaObjetivo = null;
    estado.confirmandoBorrado = false;
  } catch (problema) {
    estado.errorObjetivo = problema.message;
    estado.confirmandoBorrado = false;
  } finally {
    estado.guardando = false;
    pintar();
  }
}

// --------------------------------------------------------------------------
// Cotización del dólar
// --------------------------------------------------------------------------

/**
 * No bloquea el arranque: la app se dibuja con los movimientos y, cuando la
 * cotización llega, se repinta sola. Si no llega, la app funciona igual y el
 * botón de dólares queda desactivado.
 */
async function cargarCotizacion() {
  try {
    fijarCotizacion(await traerCotizacion());
    estado.falloCotizacion = false;
  } catch {
    fijarCotizacion(null);
    estado.falloCotizacion = true;
  }

  const boton = document.querySelector("#btn-dolar");
  boton.disabled = estado.falloCotizacion;
  boton.title = estado.falloCotizacion ? "No pude traer la cotización del dólar" : "Ver todo en dólares";

  if (!vistas.app.hidden) pintar();
}

// Volvió el internet y la última carga había fallado: se reintenta solo, sin
// que haya que tocar el botón.
addEventListener("online", () => {
  if (estado.error && !vistas.app.hidden) cargarDatos();
});

// --------------------------------------------------------------------------
// Ojo: un solo interruptor para los montos de toda la app
// --------------------------------------------------------------------------

document.querySelector("#btn-dolar").addEventListener("click", (e) => {
  const activo = alternarDolares();
  e.currentTarget.setAttribute("aria-pressed", String(activo));
  e.currentTarget.classList.toggle("es-activo", activo);
  pintar();
});

document.querySelector("#btn-ojo").addEventListener("click", (e) => {
  alternarOcultos();
  const oculto = montosOcultos();

  const boton = e.currentTarget;
  boton.setAttribute("aria-pressed", String(oculto));
  boton.classList.toggle("es-activo", oculto);
  boton.setAttribute("aria-label", oculto ? "Mostrar montos" : "Ocultar montos");
  boton.querySelector("use").setAttribute("href", oculto ? "#i-ojo-tachado" : "#i-ojo");

  pintar();
});

arrancar();
