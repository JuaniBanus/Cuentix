// Estado compartido de la app.

import { mesActual } from "./periodo.js";

function estadoInicial() {
  return {
    tab: "inicio",
    periodo: mesActual(),
    moneda: "ARS",
    monedas: ["ARS"],
    movimientos: [],
    movimientosPrevios: [],
    historialAhorros: [],
    historialGastos: [],
    serieDolar: null,

    narrativas: [],
    narrativaCargando: false,
    errorNarrativa: null,
    mesAbierto: null,

    retos: [],

    rendimientos: [],

    dolar: null,
    casaDolar: "oficial",
    falloCotizacion: false,

    objetivos: [],
    vistaObjetivo: null,
    guardando: false,
    errorObjetivo: null,
    confirmandoBorrado: false,
    inversiones: null,
    errorInversiones: null,
    precios: {},
    errorPrecios: null,
    sinCotizar: [],
    preciosMercado: {},
    errorMercado: null,
    sinCoberturaMercado: [],
    historico: null,
    insights: [],
    insightsCargando: false,
    insightsPedidos: false,
    errorInsights: null,
    categoriaAbierta: null,
    email: "",

    perfil: null,

    usuarios: [],
    errorAdmin: null,
    guardandoUsuario: null,
    error: null,
  };
}

export const estado = estadoInicial();

/** Al cerrar sesión no queda nada del usuario anterior en memoria. */
export function reiniciarEstado() {
  const limpio = estadoInicial();

  for (const clave of Object.keys(estado)) {
    if (!(clave in limpio)) delete estado[clave];
  }

  Object.assign(estado, limpio);
}
