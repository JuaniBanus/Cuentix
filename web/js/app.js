// Arranque: resuelve la sesión, trae los datos y le pasa el control al router.

import { enfocarLogin, montarLogin } from "./auth.js";
import {
  borrarObjetivo as borrarEnLaBase,
  crearObjetivo,
  editarObjetivo,
  salir,
  sesionActual,
  traerInversiones,
  traerMovimientos,
  traerObjetivos,
  traerPeriodo,
  traerRetos,
} from "./data.js";
import { borrar as borrarFoto, subir as subirFoto } from "./fotos.js";
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
import { anterior, mesActual } from "./periodo.js";
import { traerHistorico, traerPrecios } from "./mercado.js";
import { traerPreciosCripto } from "./precios.js";
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
  contenido.innerHTML = esqueletoPantalla();
  try {
    // Las dos consultas salen juntas: la comparación contra el período anterior
    // la necesita Gastos, y pedirla recién al entrar a esa pantalla dejaría un
    // hueco de carga cada vez que se toca la tab.
    const [actuales, previos, ahorros, objetivos, gastos, narrativas, retos] = await Promise.all([
      traerPeriodo(estado.periodo),
      traerPeriodo(anterior(estado.periodo)),
      // Sin acotar por fecha: la evolución del ahorro se lee sobre la historia
      // entera, no sobre el mes elegido.
      traerMovimientos({ tipo: "ahorro" }),
      traerObjetivos(),
      // Tampoco se acota: el termómetro compara el precio de un ítem entre
      // meses distintos, y con el mes elegido no vería ninguna variación.
      traerMovimientos({ tipo: "gasto" }),
      // Las dos son de solo lectura y chicas; entran en la misma tanda para
      // no agregar esperas al pintado inicial.
      traerNarrativas().catch(() => []),
      traerRetos().catch(() => []),
    ]);

    estado.movimientos = actuales;
    estado.movimientosPrevios = previos;
    estado.historialAhorros = ahorros;
    estado.historialGastos = gastos;
    estado.narrativas = narrativas;
    estado.retos = retos;

    // La serie del dólar no se espera: es de terceros y solo la usa una
    // sección. Cuando llega, se repinta. Si falla, el patrimonio se muestra
    // en pesos y lo dice.
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
