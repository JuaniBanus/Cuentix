// Pantalla Inversiones: cuánto se puso a trabajar en el período.

import { pantallaPorTipo } from "./porTipo.js";

export const renderInversiones = pantallaPorTipo({
  tipo: "inversion",
  titulo: "Inversiones",
  etiquetaTotal: "Invertido",
  vacio: "No hay inversiones en este período.",
});
