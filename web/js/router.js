// Navegación por tabs.

import { animarCifras, empezarPintado, hayQueAnimar, terminarPintado } from "./animar.js";
import { marcarActiva, montarBarra } from "./barraSecciones.js";
import { renderAviso } from "./aviso.js";
import { estado } from "./estado.js";
import { cotizacionActual } from "./format.js";
import { renderAdmin } from "./screens/admin.js";
import { renderAhorros } from "./screens/ahorros.js";
import { renderGastos } from "./screens/gastos.js";
import { renderInicio } from "./screens/inicio.js";
import { renderInversiones } from "./screens/inversiones.js";
import { renderUsuario } from "./screens/usuario.js";

export const TABS = [
  { id: "inicio", nombre: "Inicio", icono: "i-casa", render: renderInicio, datos: true,
    roles: ["usuario"] },
  { id: "gastos", nombre: "Gastos", icono: "i-gastos", render: renderGastos, datos: true,
    roles: ["usuario"] },
  { id: "ahorros", nombre: "Ahorros", icono: "i-ahorro", render: renderAhorros, datos: true,
    roles: ["usuario"] },
  { id: "inversiones", nombre: "Inversiones", icono: "i-inversion", render: renderInversiones,
    roles: ["usuario"] },
  { id: "admin", nombre: "Usuarios", icono: "i-usuario", render: renderAdmin,
    roles: ["superusuario"] },
  { id: "usuario", nombre: "Usuario", icono: "i-usuario", render: renderUsuario, aparte: true,
    roles: ["usuario", "superusuario"] },
];

/** Las secciones que le corresponden a un rol. Sin rol conocido, ninguna. */
export function tabsVisibles(rol) {
  return TABS.filter((t) => t.roles.includes(rol));
}

let nav;
let contenido;
let acciones = {};

export function montarNavegacion(opciones) {
  ({ nav, contenido, acciones } = opciones);
}

/** Dibuja la barra con las secciones del rol y deja el tab activo en una válida. */
export function armarBarra(rol) {
  const visibles = tabsVisibles(rol);
  montarBarra(nav, visibles, irA);

  if (!visibles.some((t) => t.id === estado.tab)) {
    estado.tab = visibles[0]?.id ?? "usuario";
  }
}

export function irA(tab) {
  if (estado.tab === tab) return;
  estado.tab = tab;
  acciones.alEntrarA?.(tab);
  estado.categoriaAbierta = null;
  estado.vistaObjetivo = null;
  estado.confirmandoBorrado = false;
  window.scrollTo({ top: 0 });
  pintar(true);
}

/** Redibuja la barra y la pantalla activa con el estado de ahora. */
export function pintar(conEntrada = false) {
  marcarActiva(nav, estado.tab);

  const visibles = tabsVisibles(estado.perfil?.rol);
  const actual = visibles.find((t) => t.id === estado.tab) ?? visibles[0];
  if (!actual) return;

  contenido.dataset.pantalla = actual.id;

  contenido.classList.toggle("es-nueva", conEntrada);

  if (estado.error && actual.datos) {
    renderAviso(contenido, {
      mensaje: estado.error.message,
      esDeConexion: estado.error.esDeConexion,
      onReintentar: acciones.recargar,
    });
    return;
  }

  empezarPintado(conEntrada);

  if (conEntrada) {
    contenido.classList.remove("entrando");
    requestAnimationFrame(() => contenido.classList.add("entrando"));
  }

  actual.render(contenido, {
    movimientos: estado.movimientos,
    movimientosPrevios: estado.movimientosPrevios,
    historialAhorros: estado.historialAhorros,
    historialGastos: estado.historialGastos,
    serieDolar: estado.serieDolar,
    narrativas: estado.narrativas,
    narrativaCargando: estado.narrativaCargando,
    errorNarrativa: estado.errorNarrativa,
    mesAbierto: estado.mesAbierto,
    retos: estado.retos,
    rendimientos: estado.rendimientos,
    dolar: estado.dolar,
    casaDolar: estado.casaDolar,
    setCasaDolar: acciones.setCasaDolar,
    generarNarrativa: acciones.generarNarrativa,
    verNarrativaDe: acciones.verNarrativaDe,
    hoy: new Date().toISOString().slice(0, 10),
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
    inversiones: estado.inversiones,
    errorInversiones: estado.errorInversiones,
    recargarInversiones: acciones.recargarInversiones,
    precios: estado.precios,
    errorPrecios: estado.errorPrecios,
    sinCotizar: estado.sinCotizar,
    preciosMercado: estado.preciosMercado,
    errorMercado: estado.errorMercado,
    sinCoberturaMercado: estado.sinCoberturaMercado,
    historico: estado.historico,
    verHistorico: acciones.verHistorico,
    verCerradas: estado.verCerradas,
    alternarCerradas: acciones.alternarCerradas,
    insights: estado.insights,
    insightsCargando: estado.insightsCargando,
    insightsPedidos: estado.insightsPedidos,
    errorInsights: estado.errorInsights,
    analizarGastos: acciones.analizarGastos,
    categoriaAbierta: estado.categoriaAbierta,
    email: estado.email,
    perfil: estado.perfil,
    usuarios: estado.usuarios,
    errorAdmin: estado.errorAdmin,
    guardandoUsuario: estado.guardandoUsuario,
    cambiarEstadoUsuario: acciones.cambiarEstadoUsuario,
    recargarUsuarios: acciones.recargarUsuarios,
    setMoneda: (m) => {
      estado.moneda = m;
      estado.categoriaAbierta = null;
      pintar();
    },
    setCategoria: (categoria) => {
      estado.categoriaAbierta = categoria;
      window.scrollTo({ top: 0 });
      pintar(true);
    },
    abrirObjetivo: (cual) => {
      estado.vistaObjetivo = cual;
      estado.errorObjetivo = null;
      estado.confirmandoBorrado = false;
      window.scrollTo({ top: 0 });
      pintar(true);
    },
    pedirBorrado: (si) => {
      estado.confirmandoBorrado = si;
      pintar();
    },
    guardarObjetivo: acciones.guardarObjetivo,
    borrarObjetivo: acciones.borrarObjetivo,
    onSalir: acciones.onSalir,
  });

  if (hayQueAnimar()) animarCifras(contenido);
  terminarPintado();
}
