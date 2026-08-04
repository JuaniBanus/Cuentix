// Arranque, sesión, navegación por tabs y estado compartido.

import { entrar, salir, sesionActual, traerMesActual } from "./data.js";
import { alternarOcultos, montosOcultos } from "./format.js";
import { renderInicio } from "./screens/inicio.js";

const vistas = {
  login: document.querySelector("#vista-login"),
  app: document.querySelector("#vista-app"),
};
const contenido = document.querySelector("#contenido");

const estado = {
  tab: "inicio",
  moneda: "ARS",
  movimientos: [],
  monedas: ["ARS"],
};

// --------------------------------------------------------------------------
// Sesión
// --------------------------------------------------------------------------

async function arrancar() {
  const sesion = await sesionActual();
  if (sesion) await mostrarApp();
  else mostrarLogin();
}

function mostrarLogin() {
  vistas.login.hidden = false;
  vistas.app.hidden = true;
}

async function mostrarApp() {
  vistas.login.hidden = true;
  vistas.app.hidden = false;
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
  inversiones: "Inversiones",
};

function pintar() {
  for (const boton of document.querySelectorAll(".tab")) {
    const activo = boton.dataset.tab === estado.tab;
    boton.classList.toggle("es-activo", activo);
    boton.setAttribute("aria-current", activo ? "page" : "false");
  }

  if (estado.tab === "inicio") {
    renderInicio(contenido, estado.movimientos, {
      moneda: estado.moneda,
      monedas: estado.monedas,
      setMoneda: (m) => {
        estado.moneda = m;
        pintar();
      },
    });
    return;
  }

  contenido.innerHTML = `
    <p class="vacio">${PENDIENTES[estado.tab]} llega en el próximo paso.</p>`;
}

for (const boton of document.querySelectorAll(".tab")) {
  boton.addEventListener("click", () => {
    estado.tab = boton.dataset.tab;
    pintar();
  });
}

document.querySelector("#btn-ojo").addEventListener("click", (e) => {
  alternarOcultos();
  e.currentTarget.setAttribute("aria-pressed", String(montosOcultos()));
  e.currentTarget.classList.toggle("es-activo", montosOcultos());
  pintar();
});

arrancar();
