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
import { serieDolar } from "./patrimonio.js";
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

/**
 * Muestra o esconde el período, el dólar y el ojo.
 *
 * Con `?.` a propósito. Ese grupo de botones se MUDA entre el encabezado y la
 * barra según el ancho, así que no siempre está donde uno lo dejó, y hubo un
 * momento en que directamente desaparecía del documento. Un control de
 * presentación no puede tirar abajo la función que lo llama: cerrar sesión
 * pasa por acá, y dejar a alguien adentro por no encontrar un botón es mucho
 * peor que mostrarle un botón de más.
 */
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

// --------------------------------------------------------------------------
// Sesión
// --------------------------------------------------------------------------

async function arrancar() {
  // El tema ya lo aplicó el script de index.html antes del primer pintado; acá
  // solo queda escuchar al sistema por si cambia con la app abierta.
  seguirAlSistema();
  registrarServiceWorker();

  // Los paneles de análisis de Gastos no se dibujan en pantalla angosta. Como
  // es una decisión de RENDER y no de CSS, cruzar el umbral tiene que
  // repintar: si no, achicar la ventana los dejaría puestos y agrandarla no
  // los traería hasta la próxima navegación.
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
    // Si la sesión guardada no se puede validar (token vencido, sin red),
    // se pide login de nuevo: es preferible a quedarse en la carga para siempre.
  }

  if (sesion) await abrirApp(sesion);
  else mostrarLogin();

  // Se engancha DESPUÉS de resolver la sesión inicial: registrado antes, el
  // aviso de arranque llegaría con el mismo usuario que acabamos de abrir y
  // cargaríamos todo dos veces.
  alCambiarSesion(sesionCambio);
}

/**
 * Reacciona a un cambio de sesión venga de donde venga: de esta pestaña, de
 * otra, o de supabase-js al no poder renovar el token.
 *
 * La comparación por id de usuario es la clave. Sin ella habría que elegir
 * entre recargar en cada refresco de token —que pasa solo, cada tanto— o no
 * reaccionar nunca; con ella, un refresco no hace nada y un cambio de cuenta
 * recarga todo.
 */
function sesionCambio(sesion) {
  const quien = sesion?.user?.id ?? null;

  if (quien === null) {
    // Puede llegar más de una vez (el logout propio ya pasó por acá). Es
    // idempotente a propósito: volver al login dos veces no rompe nada.
    if (usuarioEnPantalla !== null) volverAlLogin();
    return;
  }

  // Mismo usuario: fue un refresco de token y no hay nada que hacer.
  if (quien === usuarioEnPantalla) return;

  // Otro usuario entró en otra pestaña. Lo que hay en pantalla es del anterior.
  volverAlLogin();
  abrirApp(sesion);
}

function mostrarLogin() {
  mostrar("login");
  enfocarLogin();
}

// Quién está cargado en pantalla ahora mismo (el uuid, no el email). Es lo que
// distingue "se renovó el token" de "cambió la cuenta".
let usuarioEnPantalla = null;

/**
 * Decide QUÉ app se dibuja, y recién después la dibuja.
 *
 * El perfil se lee antes que cualquier dato, y el orden de las ramas no es
 * casual:
 *
 *   1. sin perfil  -> no se sabe nada de la cuenta; no se pide nada.
 *   2. contraseña provisoria -> se cambia antes de ver un solo número. Si el
 *      dashboard se dibujara primero, la provisoria ya habría servido para ver
 *      los datos y el pedido de cambio sería una sugerencia.
 *   3. cuenta no activa -> se dice el motivo. Un dashboard en cero se lee como
 *      "perdí mis datos", que es lo contrario de lo que pasó.
 *   4. superusuario -> administración, y nada de finanzas.
 *   5. resto -> el dashboard de siempre.
 *
 * Las ramas 1 a 3 salen SIN pedir movimientos. No es una optimización: es que
 * una cuenta pausada no tiene por qué generar consultas a nombre suyo.
 */
async function abrirApp(sesion) {
  usuarioEnPantalla = sesion?.user?.id ?? null;
  estado.email = sesion?.user?.email ?? "";

  let perfil = null;
  try {
    perfil = await traerPerfil(sesion.user.id);
  } catch (problema) {
    // Sin perfil no se puede decidir nada, así que tampoco se sigue de largo.
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

  // Un superusuario administra cuentas: no tiene finanzas ni pantallas para
  // mostrarlas. El período, el dólar y el ojo valen para toda la app y se
  // esconden con ella: sin movimientos no significan nada.
  const esAdmin = perfil.rol === "superusuario";

  // La barra primero: al armarla, los controles vuelven al encabezado y desde
  // ahí se reubican. Esconderlos antes se perdería en esa mudanza.
  armarBarra(perfil.rol);
  mostrarControles(!esAdmin);
  mostrar("app");

  if (esAdmin) {
    await cargarUsuarios();
    return;
  }

  await cargarDatos();
  cargarCotizacion(); // sin await: llega cuando llega
}

// Qué se le dice a cada estado que no habilita. Se distinguen porque la salida
// es distinta: una pausada se destraba avisando, una pendiente es una cuenta
// que nunca terminó de darse de alta.
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

/**
 * Borra todo rastro del usuario que se va y muestra el login.
 *
 * Son tres cosas y las tres hacen falta: el estado en memoria, el caché de
 * URLs firmadas de las fotos —que siguen funcionando sin sesión hasta que
 * vencen— y el período elegido, que si no queda puesto para el que entre.
 */
function volverAlLogin() {
  usuarioEnPantalla = null;
  reiniciarEstado();
  olvidarFirmas();
  fijarPeriodo(mesActual());
  // Los controles se esconden para el superusuario; si el próximo que entra es
  // un usuario común, tienen que estar de vuelta.
  mostrarControles(true);
  mostrarLogin();
}


// --------------------------------------------------------------------------
// Administración
// --------------------------------------------------------------------------
//
// Que estas funciones existan en el bundle no le da acceso a nadie: quien las
// llame sin ser superusuario recibe su propio perfil y nada más (RLS), y
// `admin_cambiar_estado` le contesta que no tiene permiso. La pantalla se
// esconde porque no tiene sentido mostrarla, no porque sea lo que protege.

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
    // Se relee en vez de parchear la fila en memoria: así se ve lo que quedó
    // guardado de verdad y no lo que creíamos que iba a quedar.
    estado.usuarios = await traerUsuarios();
  } catch (problema) {
    estado.errorAdmin = problema.message;
  } finally {
    estado.guardandoUsuario = null;
    pintar();
  }
}


// --------------------------------------------------------------------------
// Cambio obligatorio de contraseña
// --------------------------------------------------------------------------

/**
 * Guarda la contraseña nueva y sigue al lugar que corresponda.
 *
 * Se rearma la sesión desde cero llamando a `abrirApp`: el perfil cambió (el
 * flag bajó) y todo lo que se decide con él —qué barra, qué pantallas— hay que
 * volver a decidirlo. Parchear el flag en memoria y seguir dejaría el estado
 * diciendo una cosa y la base otra.
 */
async function guardarPassword(nueva) {
  await cambiarPassword(nueva, estado.perfil.user_id);

  const sesion = await sesionActual();
  if (sesion) await abrirApp(sesion);
  else mostrarLogin();
}

// --------------------------------------------------------------------------
// Datos
// --------------------------------------------------------------------------

async function cargarDatos() {
  contenido.innerHTML = esqueletoPantalla();
  try {
    // Las dos consultas salen juntas: la comparación contra el período anterior
    // la necesita Gastos, y pedirla recién al entrar a esa pantalla dejaría un
    // hueco de carga cada vez que se toca la tab.
    const [actuales, previos, ahorros, objetivos, gastos, narrativas, retos, rendimientos] =
      await Promise.all([
        traerPeriodo(estado.periodo),
        traerPeriodo(anterior(estado.periodo)),
        // Sin acotar por fecha: la evolución del ahorro se lee sobre la historia
        // entera, no sobre el mes elegido.
        traerMovimientos({ tipo: "ahorro" }),
        traerObjetivos(),
        // Tampoco se acota: el termómetro compara el precio de un ítem entre
        // meses distintos, y con el mes elegido no vería ninguna variación.
        traerMovimientos({ tipo: "gasto" }),
        // Las tres son de solo lectura y chicas; entran en la misma tanda para
        // no agregar esperas al pintado inicial.
        traerNarrativas().catch(() => []),
        traerRetos().catch(() => []),
        // Treinta filas de tasas públicas, sin filtro por usuario. Va acá y no
        // en un pedido diferido como el dólar porque sale de Supabase igual que
        // el resto: es el mismo viaje, no un tercero que puede tardar.
        traerRendimientos().catch(() => []),
      ]);

    estado.movimientos = actuales;
    estado.movimientosPrevios = previos;
    estado.historialAhorros = ahorros;
    estado.historialGastos = gastos;
    estado.narrativas = narrativas;
    estado.retos = retos;
    estado.rendimientos = rendimientos;

    // La serie del dólar no se espera: es de terceros y solo la usa una
    // sección. Cuando llega, se repinta. Si falla, el patrimonio se muestra
    // en pesos y lo dice.
    // Las cotizaciones tampoco se esperan: son de terceros y solo las usa el
    // panel de Gastos. traerDolar nunca lanza, devuelve el error como dato.
    if (!estado.dolar) {
      traerDolar().then((d) => {
        estado.dolar = d;
        pintar();
      });
    }

    if (!estado.serieDolar) {
      serieDolar()
        .then((serie) => {
          if (serie) {
            estado.serieDolar = serie;
            pintar();
          }
        })
        .catch(() => {});
    }
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
// Narrativa mensual
// --------------------------------------------------------------------------

/**
 * Pide el resumen del último mes cerrado y lo guarda.
 *
 * A pedido y no automático: cuesta una llamada a Gemini, y dispararla al
 * arrancar la gastaría aunque nadie la mire.
 */
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
    // El id sale de la vista: "nuevo" es alta, cualquier otra cosa es edición.
    if (estado.vistaObjetivo === "nuevo") {
      // La foto va DESPUÉS de crear: su nombre lleva el id del objetivo, que
      // recién existe cuando Postgres lo devuelve.
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
      // La anterior se borra recién cuando la fila ya no la referencia: al
      // revés, un fallo al guardar dejaría la fila apuntando a un archivo
      // que ya no existe.
      if ((foto.archivo || foto.quitar) && foto.anterior) await borrarFoto(foto.anterior);
    }

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
// Insights de gastos
// --------------------------------------------------------------------------

/**
 * Analiza los gastos y trae las recomendaciones.
 *
 * Los agregados se calculan acá, en el navegador, y al backend viajan solo
 * números: totales por categoría, variaciones y cargos repetidos. Los
 * movimientos no salen de esta máquina.
 *
 * Usa una ventana más larga que la pantalla —varios meses, no el período
 * elegido— porque con dos meses no se distingue una suscripción de una
 * casualidad. Esa consulta se hace recién acá y no en cada carga.
 */
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

// --------------------------------------------------------------------------
// Inversiones
// --------------------------------------------------------------------------

/**
 * Trae lo que una pantalla necesita y la carga inicial no pidió.
 *
 * Las tenencias y sus precios se piden al entrar a Inversiones y no al
 * arrancar: quien no invierte no tiene por qué pagar dos consultas a APIs
 * externas en cada apertura de la app.
 */
function cargarLoDelTab(tab) {
  if (tab === "inversiones" && estado.inversiones === null) cargarInversiones();
}

async function cargarInversiones() {
  try {
    estado.inversiones = await traerInversiones();
    estado.errorInversiones = null;
  } catch (problema) {
    // Se guarda el error en vez de dejar la lista vacía: "no tenés inversiones"
    // y "no pude leerlas" no son lo mismo, y mostrar lo primero cuando pasó lo
    // segundo es decirle al usuario algo falso sobre su plata.
    estado.errorInversiones = problema;
    pintar();
    return;
  }

  // Se pinta la cartera antes de ir a buscar los precios: el valor a costo o
  // el último conocido ya es información útil, y los proveedores pueden tardar.
  pintar();

  const conTicker = estado.inversiones.filter((i) => i.ticker);
  if (!conTicker.length) return;

  // Las dos fuentes son independientes y van en paralelo: CoinGecko lo consulta
  // el navegador directo y el resto pasa por el proxy del bot. Que una falle no
  // tiene por qué dejar sin valuar lo que cubre la otra.
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
    estado.errorMercado = mercado.value.error;
  } else {
    estado.errorMercado = "No pude traer los precios de mercado.";
  }

  pintar();
}

/**
 * Abre —o cierra, con null— el gráfico histórico de un activo.
 *
 * La serie se pide recién al abrir: son ~90 puntos por activo y traerlos para
 * toda la cartera al entrar sería pagar por adelantado una pantalla que casi
 * nunca se mira entera.
 */
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
    // La moneda sale del mercado y no de la posición: el gráfico muestra la
    // cotización del papel, que es en la moneda donde cotiza.
    estado.historico = {
      ticker, mercado, cargando: false, error: null, puntos,
      moneda: mercado === "ar" ? "ARS" : "USD",
    };
  } catch (problema) {
    estado.historico = { ticker, mercado, cargando: false, error: problema.message, puntos: [] };
  }
  pintar();
}

// --------------------------------------------------------------------------
// Cotizaciones
// --------------------------------------------------------------------------

let TITULO_DOLAR = null;

/**
 * No bloquea el arranque: la app se dibuja con los movimientos y, cuando las
 * cotizaciones llegan, se repinta sola. Si no llegan, la app funciona igual y
 * el botón de dólares queda desactivado.
 *
 * Se guarda con `venta` y `fecha` además de las tasas porque las pantallas ya
 * leían esos dos campos cuando la única cotización era la del dólar oficial.
 */
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
  // El title bueno —el que explica que se valúa a hoy— es el del HTML: se
  // guarda una vez y se restaura, en vez de reescribirlo acá y perderlo.
  TITULO_DOLAR ??= boton.title;
  boton.title = estado.falloCotizacion ? "No pude traer las cotizaciones" : TITULO_DOLAR;

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
