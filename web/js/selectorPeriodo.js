// El selector de período: el botón del encabezado y su panel.

import { esMismoMes, mes, MESES, rango } from "./periodo.js";

let actual;
let avisar;
let boton;
let panel;
let anioALaVista;

export function montarSelectorPeriodo({ periodoInicial, onCambio }) {
  actual = periodoInicial;
  avisar = onCambio;
  anioALaVista = actual.tipo === "mes" ? actual.anio : new Date().getFullYear();

  boton = document.querySelector("#btn-periodo");
  panel = document.querySelector("#panel-periodo");

  boton.addEventListener("click", () => (panel.hidden ? abrir() : cerrar()));

  document.addEventListener("click", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !boton.contains(e.target)) cerrar();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) {
      cerrar();
      boton.focus();
    }
  });

  mostrarEtiqueta();
}

/** Cambia el período sin avisar a nadie: para volver al mes actual al salir. */
export function fijarPeriodo(periodo) {
  actual = periodo;
  anioALaVista = periodo.tipo === "mes" ? periodo.anio : new Date().getFullYear();
  mostrarEtiqueta();
}

function mostrarEtiqueta() {
  boton.querySelector("#periodo-etiqueta").textContent = actual.etiqueta;
  boton.setAttribute("aria-label", `Período: ${actual.etiqueta}. Cambiar`);
}

function abrir() {
  dibujarPanel();
  panel.hidden = false;
  boton.setAttribute("aria-expanded", "true");
  panel.querySelector("button, input")?.focus();
}

function cerrar() {
  panel.hidden = true;
  boton.setAttribute("aria-expanded", "false");
}

function elegir(periodo) {
  actual = periodo;
  mostrarEtiqueta();
  cerrar();
  avisar(periodo);
}


function dibujarPanel() {
  const hoy = new Date();
  const esRango = actual.tipo === "rango";

  panel.innerHTML = `
    <div class="panel-modos" role="group" aria-label="Tipo de período">
      <button class="chip ${esRango ? "" : "es-activo"}" data-modo="mes">Mes</button>
      <button class="chip ${esRango ? "es-activo" : ""}" data-modo="rango">Rango</button>
    </div>

    <div class="panel-cuerpo">
      ${esRango ? cuerpoRango() : cuerpoMes(hoy)}
    </div>`;

  for (const chip of panel.querySelectorAll("[data-modo]")) {
    chip.addEventListener("click", () => {
      const cuerpo = panel.querySelector(".panel-cuerpo");
      const aRango = chip.dataset.modo === "rango";
      for (const otro of panel.querySelectorAll("[data-modo]")) {
        otro.classList.toggle("es-activo", otro === chip);
      }
      cuerpo.innerHTML = aRango ? cuerpoRango() : cuerpoMes(hoy);
      engancharCuerpo(hoy);
    });
  }

  engancharCuerpo(hoy);
}

function cuerpoMes(hoy) {
  const grilla = MESES.map((nombre, i) => {
    const elegido = esMismoMes(actual, anioALaVista, i);
    const esteMes = anioALaVista === hoy.getFullYear() && i === hoy.getMonth();
    return `
      <button class="mes ${elegido ? "es-activo" : ""} ${esteMes ? "es-hoy" : ""}"
              data-mes="${i}" ${elegido ? 'aria-current="true"' : ""}>
        ${nombre.slice(0, 3)}
      </button>`;
  }).join("");

  return `
    <div class="panel-anio">
      <button class="boton-icono" data-anio="-1" aria-label="Año anterior">
        <svg viewBox="0 0 24 24" class="icono"><use href="#i-izquierda"></use></svg>
      </button>
      <span class="panel-anio-numero">${anioALaVista}</span>
      <button class="boton-icono" data-anio="1" aria-label="Año siguiente">
        <svg viewBox="0 0 24 24" class="icono"><use href="#i-derecha"></use></svg>
      </button>
    </div>
    <div class="panel-meses">${grilla}</div>`;
}

function cuerpoRango() {
  return `
    <form class="panel-rango">
      <label class="campo">
        <span>Desde</span>
        <input type="date" name="desde" value="${actual.desde}" required>
      </label>
      <label class="campo">
        <span>Hasta</span>
        <input type="date" name="hasta" value="${actual.hasta}" required>
      </label>
      <button type="submit" class="boton boton-acento">Aplicar</button>
    </form>`;
}

function engancharCuerpo(hoy) {
  for (const flecha of panel.querySelectorAll("[data-anio]")) {
    flecha.addEventListener("click", () => {
      anioALaVista += Number(flecha.dataset.anio);
      panel.querySelector(".panel-cuerpo").innerHTML = cuerpoMes(hoy);
      engancharCuerpo(hoy);
    });
  }

  for (const botonMes of panel.querySelectorAll("[data-mes]")) {
    elegirAlTocar(botonMes);
  }

  panel.querySelector(".panel-rango")?.addEventListener("submit", (e) => {
    e.preventDefault();
    elegir(rango(e.target.desde.value, e.target.hasta.value));
  });
}

function elegirAlTocar(botonMes) {
  botonMes.addEventListener("click", () => {
    elegir(mes(anioALaVista, Number(botonMes.dataset.mes)));
  });
}
