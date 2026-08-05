// Navegación por tabs.
//
// TABS es la fuente única: de esta lista salen los botones de la barra inferior
// y también la pantalla que se pinta. Agregar una sección es agregar una línea,
// no tocar el HTML y el JS por separado y esperar que queden sincronizados.

import { renderAviso } from "./aviso.js";
import { estado } from "./estado.js";
import { cotizacionActual } from "./format.js";
import { renderAhorros } from "./screens/ahorros.js";
import { renderGastos } from "./screens/gastos.js";
import { renderInicio } from "./screens/inicio.js";
import { renderInversiones } from "./screens/inversiones.js";
import { renderUsuario } from "./screens/usuario.js";

// `datos: true` marca las que no tienen nada que mostrar si la consulta falló.
// Usuario no lleva la marca a propósito: sin internet igual se tiene que poder
// cambiar el tema y cerrar sesión.
export const TABS = [
  { id: "inicio", nombre: "Inicio", icono: "i-casa", render: renderInicio, datos: true },
  { id: "gastos", nombre: "Gastos", icono: "i-gastos", render: renderGastos, datos: true },
  { id: "ahorros", nombre: "Ahorros", icono: "i-ahorro", render: renderAhorros, datos: true },
  { id: "inversiones", nombre: "Inversiones", icono: "i-inversion", render: renderInversiones, datos: true },
  { id: "usuario", nombre: "Usuario", icono: "i-usuario", render: renderUsuario },
];

let nav;
let contenido;
let acciones = {};

/** @param {{nav: HTMLElement, contenido: HTMLElement, acciones: object}} opciones */
export function montarNavegacion(opciones) {
  ({ nav, contenido, acciones } = opciones);

  nav.innerHTML = TABS.map(
    (t) => `
      <button class="tab" data-tab="${t.id}" aria-current="false">
        <svg viewBox="0 0 24 24" class="icono"><use href="#${t.icono}"></use></svg>
        <span>${t.nombre}</span>
      </button>`
  ).join("");

  for (const boton of nav.querySelectorAll(".tab")) {
    boton.addEventListener("click", () => irA(boton.dataset.tab));
  }
}

export function irA(tab) {
  if (estado.tab === tab) return;
  estado.tab = tab;
  estado.categoriaAbierta = null;
  estado.vistaObjetivo = null;
  estado.confirmandoBorrado = false;
  // Cambiar de sección arranca arriba: si venías scrolleado en Inicio, la
  // pantalla nueva empezaría por la mitad.
  window.scrollTo({ top: 0 });
  pintar();
}

/** Redibuja la barra y la pantalla activa con el estado de ahora. */
export function pintar() {
  for (const boton of nav.querySelectorAll(".tab")) {
    const activo = boton.dataset.tab === estado.tab;
    boton.classList.toggle("es-activo", activo);
    boton.setAttribute("aria-current", activo ? "page" : "false");
  }

  const actual = TABS.find((t) => t.id === estado.tab) ?? TABS[0];

  if (estado.error && actual.datos) {
    renderAviso(contenido, {
      mensaje: estado.error.message,
      esDeConexion: estado.error.esDeConexion,
      onReintentar: acciones.recargar,
    });
    return;
  }

  // Todas las pantallas reciben el mismo contexto, así ninguna necesita
  // importar el estado ni saber cómo se recarga.
  actual.render(contenido, {
    movimientos: estado.movimientos,
    movimientosPrevios: estado.movimientosPrevios,
    historialAhorros: estado.historialAhorros,
    cotizacion: cotizacionActual(),
    falloCotizacion: estado.falloCotizacion,
    objetivos: estado.objetivos,
    vistaObjetivo: estado.vistaObjetivo,
    guardando: estado.guardando,
    errorObjetivo: estado.errorObjetivo,
    confirmandoBorrado: estado.confirmandoBorrado,
    periodo: estado.periodo,
    moneda: estado.moneda,
    monedas: estado.monedas,
    categoriaAbierta: estado.categoriaAbierta,
    email: estado.email,
    setMoneda: (m) => {
      estado.moneda = m;
      // Cambiar de moneda cierra el detalle: la categoría abierta podría no
      // existir en la otra, y quedaría una pantalla de ceros.
      estado.categoriaAbierta = null;
      pintar();
    },
    setCategoria: (categoria) => {
      estado.categoriaAbierta = categoria;
      window.scrollTo({ top: 0 });
      pintar();
    },
    abrirObjetivo: (cual) => {
      estado.vistaObjetivo = cual;
      estado.errorObjetivo = null;
      estado.confirmandoBorrado = false;
      window.scrollTo({ top: 0 });
      pintar();
    },
    pedirBorrado: (si) => {
      estado.confirmandoBorrado = si;
      pintar();
    },
    guardarObjetivo: acciones.guardarObjetivo,
    borrarObjetivo: acciones.borrarObjetivo,
    onSalir: acciones.onSalir,
  });
}
