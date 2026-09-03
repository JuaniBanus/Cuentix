// Arranque: resuelve la sesión, trae los datos y le pasa el control al router.

import { enfocarLogin, montarLogin } from "./auth.js";
import {
  alCambiarSesion,
  borrarObjetivo as borrarEnLaBase,
  cambiarEstadoUsuario as cambiarEstadoEnLaBase,
  cambiarPassword,
  crearObjetivo,
  editarObjetivo,
  salir,
  sesionActual,
  traerInversiones,
  traerMovimientos,
  traerObjetivos,
  traerPerfil,
  traerPeriodo,
  traerRendimientos,
  traerRetos,
  traerUsuarios,
} from "./data.js";
import { enfocarPassword, montarPassword } from "./password.js";
import { traerDolar } from "./dolar.js";
import { borrar as borrarFoto, olvidarFirmas, subir as subirFoto } from "./fotos.js";
import {
  agregados as agregadosDelMes,
  generarYGuardar,
  traerNarrativas,
  ultimoMesCerrado,
} from "./narrativa.js";
import { resumenDeTasas, traerCotizaciones } from "./cotizaciones.js";
import { esqueletoPantalla } from "./esqueleto.js";
import { estado, reiniciarEstado } from "./estado.js";
import { MESES_ANALIZADOS, armarAgregados, pedirInsights } from "./insights.js";
import { alternarDolares, alternarOcultos, fijarCotizacion, montosOcultos } from "./format.js";
import { alCambiarDeTamano } from "./pantalla.js";
import { anterior, mesActual } from "./periodo.js";
import { traerHistorico, traerPrecios } from "./mercado.js";
import { traerPreciosCripto } from "./precios.js";
import { registrarServiceWorker } from "./pwa.js";
import { armarBarra, montarNavegacion, pintar } from "./router.js";
import { fijarPeriodo, montarSelectorPeriodo } from "./selectorPeriodo.js";
import { seguirAlSistema } from "./tema.js";

const vistas = {
  carga: document.querySelector("#vista-carga"),
  login: document.querySelector("#vista-login"),
  password: document.querySelector("#vista-password"),
  estado: document.querySelector("#vista-estado"),
  app: document.querySelector("#vista-app"),
};

/** Una sola vista visible a la vez: login y app nunca conviven en pantalla. */
function mostrar(cual) {
  for (const [nombre, nodo] of Object.entries(vistas)) nodo.hidden = nombre !== cual;
}

/** Muestra o esconde el período, el dólar y el ojo. */
function mostrarControles(visible) {
  const controles = document.querySelector(".cabecera-acciones");
  if (controles) controles.hidden = !visible;
}

/** La vista de cuenta sin acceso, con el motivo escrito. */
function mostrarEstado(titulo, detalle) {
  document.querySelector("#estado-titulo").textContent = titulo;
  document.querySelector("#estado-detalle").textContent = detalle;
  mostrar("estado");
}

const contenido = document.querySelector("#contenido");


async function arrancar() {
  seguirAlSistema();
  registrarServiceWorker();

  alCambiarDeTamano(() => pintar());

  montarNavegacion({
    nav: document.querySelector("#tabs"),
    contenido,
    acciones: {
      onSalir: cerrarSesion,
      recargar: cargarDatos,
      guardarObjetivo,
      borrarObjetivo,
      alEntrarA: cargarLoDelTab,
      recargarInversiones: cargarInversiones,
      verHistorico,
      alternarCerradas: (abierto) => {
        estado.verCerradas = abierto;
        pintar();
      },
      analizarGastos,
      generarNarrativa,
      verNarrativaDe,
      cambiarEstadoUsuario,
      recargarUsuarios: cargarUsuarios,
      setCasaDolar: (casa) => {
        estado.casaDolar = casa;
        pintar();
      },
    },
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
  montarPassword(guardarPassword);
  document.querySelector("#btn-salir-estado").addEventListener("click", cerrarSesion);

  let sesion = null;
  try {
    sesion = await sesionActual();
  } catch {
  }

  if (sesion) await abrirApp(sesion);
  else mostrarLogin();

  alCambiarSesion(sesionCambio);
}

/** Reacciona a un cambio de sesión venga de donde venga: de esta pestaña, de */
function sesionCambio(sesion) {
  const quien = sesion?.user?.id ?? null;

  if (quien === null) {
    if (usuarioEnPantalla !== null) volverAlLogin();
    return;
  }

  if (quien === usuarioEnPantalla) return;

  volverAlLogin();
  abrirApp(sesion);
}

function mostrarLogin() {
  mostrar("login");
  enfocarLogin();
}

let usuarioEnPantalla = null;

/** Decide QUÉ app se dibuja, y recién después la dibuja. */
async function abrirApp(sesion) {
  usuarioEnPantalla = sesion?.user?.id ?? null;
  estado.email = sesion?.user?.email ?? "";

  let perfil = null;
  try {
    perfil = await traerPerfil(sesion.user.id);
  } catch (problema) {
    mostrarEstado("No pude leer tu cuenta", problema.message);
    return;
  }

  estado.perfil = perfil;

  if (!perfil) {
    mostrarEstado(
      "Tu cuenta no está configurada",
      "Existe el usuario pero le falta el perfil. Avisale al administrador."
    );
    return;
  }

  if (perfil.debe_cambiar_password) {
    mostrar("password");
    enfocarPassword();
    return;
  }

  if (perfil.estado !== "activo") {
    mostrarEstado(...(MOTIVO[perfil.estado] ?? MOTIVO.pendiente));
    return;
  }

  const esAdmin = perfil.rol === "superusuario";

  armarBarra(perfil.rol);
  mostrarControles(!esAdmin);
  mostrar("app");

  if (esAdmin) {
    await cargarUsuarios();
    return;
  }

  await cargarDatos();
  cargarCotizacion();
}

const MOTIVO = {
  pausado: [
    "Tu cuenta está pausada",
    "No podés entrar por ahora. Tus datos están intactos: cuando el " +
      "administrador la reactive, vuelve todo como estaba.",
  ],
  pendiente: [
    "Tu cuenta todavía no está habilitada",
    "Ya existe, pero falta que el administrador la active. Escribile y listo.",
  ],
};

async function cerrarSesion() {
  await salir();
  volverAlLogin();
}

/** Borra todo rastro del usuario que se va y muestra el login. */
function volverAlLogin() {
  usuarioEnPantalla = null;
  reiniciarEstado();
  olvidarFirmas();
  fijarPeriodo(mesActual());
  mostrarControles(true);
  mostrarLogin();
}


async function cargarUsuarios() {
  try {
    estado.usuarios = await traerUsuarios();
    estado.errorAdmin = null;
  } catch (problema) {
    estado.errorAdmin = problema.message;
  }
  pintar();
}

async function cambiarEstadoUsuario(userId, nuevoEstado) {
  estado.guardandoUsuario = userId;
  estado.errorAdmin = null;
  pintar();

  try {
    await cambiarEstadoEnLaBase(userId, nuevoEstado);
    estado.usuarios = await traerUsuarios();
  } catch (problema) {
    estado.errorAdmin = problema.message;
  } finally {
    estado.guardandoUsuario = null;
    pintar();
  }
}


/** Guarda la contraseña nueva y sigue al lugar que corresponda. */
async function guardarPassword(nueva) {
  await cambiarPassword(nueva, estado.perfil.user_id);

  const sesion = await sesionActual();
  if (sesion) await abrirApp(sesion);
  else mostrarLogin();
}


async function cargarDatos() {
  contenido.innerHTML = esqueletoPantalla();
  try {
    const [actuales, previos, ahorros, objetivos, gastos, narrativas, retos, rendimientos] =
      await Promise.all([
        traerPeriodo(estado.periodo),
        traerPeriodo(anterior(estado.periodo)),
        traerMovimientos({ tipo: "ahorro" }),
        traerObjetivos(),
        traerMovimientos({ tipo: "gasto" }),
        traerNarrativas().catch(() => []),
        traerRetos().catch(() => []),
        traerRendimientos().catch(() => []),
      ]);

    estado.movimientos = actuales;
    estado.movimientosPrevios = previos;
    estado.historialAhorros = ahorros;
    estado.historialGastos = gastos;
    estado.narrativas = narrativas;
    estado.retos = retos;
    estado.rendimientos = rendimientos;

    if (!estado.dolar) {
      traerDolar().then((d) => {
        estado.dolar = d;
        pintar();
      });
    }

    estado.objetivos = objetivos;
    estado.error = null;

    const presentes = [...new Set(estado.movimientos.map((m) => m.moneda))];
    estado.monedas = presentes.length ? presentes.sort() : ["ARS"];
    if (!estado.monedas.includes(estado.moneda)) estado.moneda = estado.monedas[0];
  } catch (problema) {
    estado.error = problema;
    estado.movimientos = [];
    estado.movimientosPrevios = [];
    estado.historialAhorros = [];
    estado.objetivos = [];
  }
  pintar();
}


/** Pide el resumen del último mes cerrado y lo guarda. */
async function generarNarrativa() {
  const mes = ultimoMesCerrado();
  estado.narrativaCargando = true;
  estado.errorNarrativa = null;
  pintar();

  try {
    const datos = agregadosDelMes(
      estado.historialGastos.concat(estado.historialAhorros ?? []),
      estado.objetivos,
      mes,
      estado.moneda
    );
    await generarYGuardar(datos, mes);
    estado.narrativas = await traerNarrativas();
    estado.mesAbierto = mes;
  } catch (problema) {
    estado.errorNarrativa = problema.message;
  } finally {
    estado.narrativaCargando = false;
    pintar();
  }
}

function verNarrativaDe(mes) {
  estado.mesAbierto = mes;
  pintar();
}


/** Lo que se puede rechazar sin molestar al servidor. Los checks de la tabla */
function revisar(datos) {
  if (!datos.nombre) return "Poné un nombre.";

  const monto = Number(datos.monto_objetivo);
  if (!Number.isFinite(monto) || monto <= 0) return "El monto tiene que ser mayor que cero.";
  if (monto > 99_999_999_999.99) return "Ese monto no entra en la base.";

  return null;
}

async function guardarObjetivo(datos, foto = {}) {
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
    if (estado.vistaObjetivo === "nuevo") {
      const creado = await crearObjetivo(datos);
      if (foto.archivo && creado?.id) {
        const ruta = await subirFoto(foto.archivo, creado.id);
        await editarObjetivo(creado.id, { foto_path: ruta });
      }
    } else {
      const cambios = { ...datos };
      if (foto.archivo) {
        cambios.foto_path = await subirFoto(foto.archivo, estado.vistaObjetivo);
      } else if (foto.quitar) {
        cambios.foto_path = null;
      }
      await editarObjetivo(estado.vistaObjetivo, cambios);
      if ((foto.archivo || foto.quitar) && foto.anterior) await borrarFoto(foto.anterior);
    }

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


/** Analiza los gastos y trae las recomendaciones. */
async function analizarGastos() {
  if (estado.insightsCargando) return;

  estado.insightsCargando = true;
  estado.errorInsights = null;
  pintar();

  try {
    const desde = mesesAtras(estado.periodo, MESES_ANALIZADOS);
    const historial = await traerMovimientos({ desde, hasta: estado.periodo.hasta });

    const agregados = armarAgregados({
      movimientos: estado.movimientos,
      previos: estado.movimientosPrevios,
      historial,
      moneda: estado.moneda,
      etiquetaPeriodo: estado.periodo.etiqueta,
    });

    estado.insights = await pedirInsights(agregados);
    estado.insightsPedidos = true;
  } catch (problema) {
    estado.errorInsights = problema.message;
  } finally {
    estado.insightsCargando = false;
    pintar();
  }
}

/** El primer día del mes que está `cantidad` meses antes del período. */
function mesesAtras(periodo, cantidad) {
  const [anio, mes] = periodo.desde.split("-").map(Number);
  const fecha = new Date(anio, mes - 1 - cantidad, 1);
  const mm = String(fecha.getMonth() + 1).padStart(2, "0");
  return `${fecha.getFullYear()}-${mm}-01`;
}


/** Trae lo que una pantalla necesita y la carga inicial no pidió. */
function cargarLoDelTab(tab) {
  if (tab === "inversiones" && estado.inversiones === null) cargarInversiones();
}

async function cargarInversiones() {
  try {
    estado.inversiones = await traerInversiones();
    estado.errorInversiones = null;
  } catch (problema) {
    estado.errorInversiones = problema;
    pintar();
    return;
  }

  pintar();

  const conTicker = estado.inversiones.filter((i) => i.ticker && i.activa);
  if (!conTicker.length) return;

  const [cripto, mercado] = await Promise.allSettled([
    traerPreciosCripto(conTicker.map((i) => i.ticker)),
    traerPrecios(conTicker),
  ]);

  if (cripto.status === "fulfilled") {
    estado.precios = cripto.value.precios;
    estado.sinCotizar = cripto.value.sinCotizar;
    estado.errorPrecios = cripto.value.error;
  }

  if (mercado.status === "fulfilled") {
    estado.preciosMercado = mercado.value.precios;
    estado.sinCoberturaMercado = mercado.value.sinCobertura;
    estado.errorMercado = mercado.value.error || mercado.value.aviso;
    estado.cupoMercado = mercado.value.cupo;
  } else {
    estado.errorMercado = "No pude traer los precios de mercado.";
  }

  pintar();
}

/** Abre —o cierra, con null— el gráfico histórico de un activo. */
async function verHistorico(ticker, mercado) {
  if (!ticker) {
    estado.historico = null;
    pintar();
    return;
  }

  estado.historico = { ticker, mercado, cargando: true, error: null, puntos: [], moneda: null };
  pintar();

  try {
    const puntos = await traerHistorico(ticker, mercado);
    estado.historico = {
      ticker, mercado, cargando: false, error: null, puntos,
      moneda: mercado === "ar" ? "ARS" : "USD",
    };
  } catch (problema) {
    estado.historico = { ticker, mercado, cargando: false, error: problema.message, puntos: [] };
  }
  pintar();
}


let TITULO_DOLAR = null;

/** No bloquea el arranque: la app se dibuja con los movimientos y, cuando las */
async function cargarCotizacion() {
  try {
    const cotizaciones = await traerCotizaciones();
    fijarCotizacion({
      venta: cotizaciones.arsPorUsd,
      fecha: cotizaciones.actualizado ?? "",
      vencida: false,
      tasas: cotizaciones.tasas,
      eurAproximado: cotizaciones.eurAproximado,
      resumen: resumenDeTasas(cotizaciones),
    });
    estado.falloCotizacion = false;
  } catch {
    fijarCotizacion(null);
    estado.falloCotizacion = true;
  }

  const boton = document.querySelector("#btn-dolar");
  boton.disabled = estado.falloCotizacion;
  TITULO_DOLAR ??= boton.title;
  boton.title = estado.falloCotizacion ? "No pude traer las cotizaciones" : TITULO_DOLAR;

  if (!vistas.app.hidden) pintar();
}

addEventListener("online", () => {
  if (estado.error && !vistas.app.hidden) cargarDatos();
});


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
