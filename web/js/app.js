// Arranque, sesión, navegación por tabs y estado compartido.

import {
  convertirMovimientos,
  monedasSinConvertir,
  resumenDeTasas,
  traerCotizaciones,
} from "./cotizaciones.js";
import { entrar, salir, sesionActual, traerInversiones, traerMesActual } from "./data.js";
import { alternarOcultos, esc, montosOcultos } from "./format.js";
import { traerPreciosCripto } from "./precios.js";
import { renderInicio } from "./screens/inicio.js";
import { renderInversiones } from "./screens/inversiones.js";

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
const avisoUSD = document.querySelector("#aviso-usd");
const botonUSD = document.querySelector("#btn-usd");

// El toggle se guarda en localStorage y no solo en memoria: "que se mantenga al
// navegar" incluye volver a abrir la app, no únicamente cambiar de tab.
const CLAVE_USD = "cuentix:ver-en-usd";

const estado = {
  tab: "inicio",
  moneda: "ARS",
  movimientos: [],
  monedas: ["ARS"],
  // Modo de conversión: apagado por defecto. La vista natural es cada moneda
  // por separado; convertir es una lectura derivada que el usuario pide.
  enUSD: localStorage.getItem(CLAVE_USD) === "1",
  cotizaciones: null,
  errorCotizaciones: null,
  // null = todavía no se entró al tab. [] = se entró y no hay tenencias.
  inversiones: null,
  precios: {},
  errorPrecios: null,
  sinCotizar: [],
};

/**
 * Lo que se dibuja: los movimientos tal cual, o convertidos a USD.
 *
 * Devuelve la misma forma en los dos casos —lista de movimientos con `monto` y
 * `moneda`, más las monedas presentes—, así que las pantallas no necesitan
 * saber si hubo conversión. Ese es todo el truco para unificarlo en TODAS sin
 * tocar cada una.
 */
function vista() {
  if (!estado.enUSD || !estado.cotizaciones) {
    return {
      movimientos: estado.movimientos,
      monedas: estado.monedas,
      moneda: estado.moneda,
    };
  }

  const convertidos = convertirMovimientos(estado.movimientos, estado.cotizaciones);
  const presentes = [...new Set(convertidos.map((m) => m.moneda))].sort();
  const monedas = presentes.length ? presentes : ["USD"];

  return {
    movimientos: convertidos,
    monedas,
    // Si algo no se pudo convertir quedan dos grupos; USD manda igual.
    moneda: monedas.includes("USD") ? "USD" : monedas[0],
  };
}

// --------------------------------------------------------------------------
// Sesión
// --------------------------------------------------------------------------

async function arrancar() {
  let sesion = null;
  try {
    sesion = await sesionActual();
  } catch {
    // Si la sesión guardada no se puede validar (token vencido, sin red),
    // se pide login de nuevo: es preferible a quedarse en la carga para siempre.
  }
  if (sesion) await mostrarApp();
  else mostrarLogin();
}

function mostrarLogin() {
  mostrar("login");
  document.querySelector("#form-login").email.focus();
}

async function mostrarApp() {
  mostrar("app");
  await cargarDatos();
}

document.querySelector("#form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const error = document.querySelector("#login-error");
  const boton = e.target.querySelector("button");

  error.textContent = "";
  boton.disabled = true;
  boton.textContent = "Entrando…";

  try {
    await entrar(e.target.email.value.trim(), e.target.password.value);
    await mostrarApp();
  } catch (err) {
    error.textContent = err.message;
  } finally {
    boton.disabled = false;
    boton.textContent = "Entrar";
  }
});

document.querySelector("#btn-salir").addEventListener("click", async () => {
  await salir();
  estado.movimientos = [];
  mostrarLogin();
});

// --------------------------------------------------------------------------
// Datos
// --------------------------------------------------------------------------

async function cargarDatos() {
  contenido.innerHTML = `<p class="cargando">Cargando…</p>`;
  try {
    estado.movimientos = await traerMesActual();

    // Las monedas salen de los datos, no de una lista fija: si nunca cargaste
    // un gasto en dólares, el selector no aparece.
    const presentes = [...new Set(estado.movimientos.map((m) => m.moneda))];
    estado.monedas = presentes.length ? presentes.sort() : ["ARS"];
    if (!estado.monedas.includes(estado.moneda)) estado.moneda = estado.monedas[0];

    // El toggle sobrevive al cierre de la app, así que puede venir encendido
    // sin que nadie lo haya tocado en esta sesión: hay que traer las tasas.
    if (estado.enUSD && !estado.cotizaciones) {
      try {
        estado.cotizaciones = await traerCotizaciones();
      } catch (err) {
        estado.enUSD = false;
        localStorage.setItem(CLAVE_USD, "0");
        estado.errorCotizaciones = err.message;
      }
    }

    pintar();
  } catch (err) {
    contenido.innerHTML = `
      <p class="vacio">No pude traer los movimientos.<br>
      <span class="apunte">${err.message}</span></p>`;
  }
}

// --------------------------------------------------------------------------
// Navegación
// --------------------------------------------------------------------------

const PENDIENTES = {
  gastos: "Gastos",
  ahorros: "Ahorros",
};

/**
 * Carga las inversiones y sus precios la primera vez que se entra al tab.
 *
 * No se traen en el arranque junto con los movimientos: quien entra a mirar el
 * balance del mes no debería esperar dos consultas más y una llamada a
 * CoinGecko que quizá no mire nunca.
 */
async function cargarInversiones() {
  if (estado.inversiones) return;

  contenido.innerHTML = `<p class="cargando">Cargando…</p>`;
  estado.inversiones = await traerInversiones();

  const tickersCripto = estado.inversiones
    .filter((i) => i.tipo === "cripto")
    .map((i) => i.ticker);

  if (tickersCripto.length) {
    // traerPreciosCripto nunca lanza: devuelve el error como dato para que la
    // cartera se vea igual aunque CoinGecko esté caído.
    const resultado = await traerPreciosCripto(tickersCripto);
    estado.precios = resultado.precios;
    estado.errorPrecios = resultado.error;
    estado.sinCotizar = resultado.sinCotizar;
  }

  // Las cotizaciones hacen falta acá aunque el toggle "ver todo en USD" esté
  // apagado: las distribuciones porcentuales necesitan una moneda común para
  // no comparar pesos contra dólares uno a uno.
  if (!estado.cotizaciones) {
    try {
      estado.cotizaciones = await traerCotizaciones();
    } catch {
      // La pantalla lo resuelve: muestra las posiciones y avisa que no puede
      // dibujar el reparto porcentual.
    }
  }
}

function pintar() {
  for (const boton of document.querySelectorAll(".tab")) {
    const activo = boton.dataset.tab === estado.tab;
    boton.classList.toggle("es-activo", activo);
    boton.setAttribute("aria-current", activo ? "page" : "false");
  }

  pintarAvisoUSD();
  const actual = vista();

  if (estado.tab === "inicio") {
    renderInicio(contenido, actual.movimientos, {
      moneda: actual.moneda,
      monedas: actual.monedas,
      setMoneda: (m) => {
        // En modo USD la moneda elegida es la de la vista, no la del estado
        // de fondo: si no, apagar el toggle dejaría seleccionada una moneda
        // que no existe en los datos originales.
        if (estado.enUSD) return;
        estado.moneda = m;
        pintar();
      },
    });
    return;
  }

  if (estado.tab === "inversiones") {
    renderInversiones(contenido, estado.inversiones ?? [], {
      precios: estado.precios,
      errorPrecios: estado.errorPrecios,
      sinCotizar: estado.sinCotizar,
      cotizaciones: estado.cotizaciones,
    });
    return;
  }

  contenido.innerHTML = `
    <p class="vacio">${PENDIENTES[estado.tab]} llega en el próximo paso.</p>`;
}

/** La línea bajo la cabecera que explica de dónde salen los números. */
function pintarAvisoUSD() {
  botonUSD.setAttribute("aria-pressed", String(estado.enUSD));
  botonUSD.classList.toggle("es-activo", estado.enUSD);
  avisoUSD.classList.remove("es-error");

  if (!estado.enUSD) {
    avisoUSD.hidden = true;
    avisoUSD.innerHTML = "";
    return;
  }

  avisoUSD.hidden = false;

  if (estado.errorCotizaciones) {
    avisoUSD.classList.add("es-error");
    avisoUSD.textContent = `Sin conversión: ${estado.errorCotizaciones}`;
    return;
  }
  if (!estado.cotizaciones) {
    avisoUSD.textContent = "Buscando cotizaciones…";
    return;
  }

  const sinConvertir = monedasSinConvertir(estado.movimientos, estado.cotizaciones);
  const pendiente = sinConvertir.length
    ? ` · ${esc(sinConvertir.join(", "))} sin cotización, se muestra aparte`
    : "";

  avisoUSD.innerHTML =
    `<span class="aviso-destacado">Valuado a hoy</span> · ` +
    `${esc(resumenDeTasas(estado.cotizaciones))}${pendiente}`;
}

/** Enciende o apaga la conversión, trayendo las cotizaciones la primera vez. */
async function alternarUSD() {
  estado.enUSD = !estado.enUSD;
  localStorage.setItem(CLAVE_USD, estado.enUSD ? "1" : "0");

  if (!estado.enUSD) {
    pintar();
    return;
  }

  if (estado.cotizaciones) {
    pintar();
    return;
  }

  estado.errorCotizaciones = null;
  botonUSD.disabled = true;
  pintar(); // muestra "Buscando cotizaciones…"

  try {
    estado.cotizaciones = await traerCotizaciones();
  } catch (err) {
    // Se apaga el modo: dejarlo encendido sin tasas mostraría los montos
    // originales bajo un cartel que promete dólares.
    estado.enUSD = false;
    localStorage.setItem(CLAVE_USD, "0");
    estado.errorCotizaciones = err.message;
    avisoUSD.hidden = false;
    avisoUSD.classList.add("es-error");
    avisoUSD.textContent = `No pude convertir a USD: ${err.message}`;
    botonUSD.disabled = false;
    botonUSD.setAttribute("aria-pressed", "false");
    botonUSD.classList.remove("es-activo");
    return;
  } finally {
    botonUSD.disabled = false;
  }

  pintar();
}

for (const boton of document.querySelectorAll(".tab")) {
  boton.addEventListener("click", async () => {
    estado.tab = boton.dataset.tab;

    if (estado.tab === "inversiones") {
      try {
        await cargarInversiones();
      } catch (err) {
        contenido.innerHTML = `
          <p class="vacio">No pude traer las inversiones.<br>
          <span class="apunte">${esc(err.message)}</span></p>`;
        return;
      }
    }

    pintar();
  });
}

botonUSD.addEventListener("click", alternarUSD);

document.querySelector("#btn-ojo").addEventListener("click", (e) => {
  alternarOcultos();
  e.currentTarget.setAttribute("aria-pressed", String(montosOcultos()));
  e.currentTarget.classList.toggle("es-activo", montosOcultos());
  pintar();
});

arrancar();
