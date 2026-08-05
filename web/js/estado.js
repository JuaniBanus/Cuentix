// Estado compartido de la app.
//
// Vive en su propio módulo y no en app.js para que el router pueda leerlo sin
// que los dos se importen en círculo.

import { mesActual } from "./periodo.js";

export const estado = {
  tab: "inicio",
  // El período vale para toda la app y sobrevive al cambio de tab, porque vive
  // acá y no adentro de una pantalla.
  periodo: mesActual(),
  moneda: "ARS",
  monedas: ["ARS"],
  movimientos: [],
  // Los del período anterior equivalente. Se traen siempre junto con los
  // actuales para poder comparar sin una segunda vuelta a la red al entrar a
  // Gastos.
  movimientosPrevios: [],
  // Todos los ahorros, sin acotar por período: el ahorro es un stock y su
  // evolución solo se lee mirando la historia entera.
  historialAhorros: [],
  // La cotización la guarda format.js, que es quien convierte. Acá solo queda
  // si el pedido falló, para poder avisarlo en pantalla.
  falloCotizacion: false,

  // Objetivos de ahorro. La única tabla donde la web escribe.
  objetivos: [],
  // null = la lista; "nuevo" = el formulario vacío; un id = editando ese.
  vistaObjetivo: null,
  guardando: false,
  errorObjetivo: null,
  confirmandoBorrado: false,
  // Categoría abierta en Gastos. Vive acá y no adentro de la pantalla porque
  // cada toque del ojo la redibuja entera, y una variable local se perdería.
  categoriaAbierta: null,
  email: "",
  // Si los datos no se pudieron traer, acá queda el ErrorAmable. Las pantallas
  // que dependen de datos muestran el aviso en vez de dibujar un mes vacío,
  // que sería mentir: "sin movimientos" y "no pude leer" no son lo mismo.
  error: null,
};

/** Al cerrar sesión no queda nada del usuario anterior en memoria. */
export function reiniciarEstado() {
  estado.tab = "inicio";
  estado.periodo = mesActual();
  estado.moneda = "ARS";
  estado.monedas = ["ARS"];
  estado.movimientos = [];
  estado.movimientosPrevios = [];
  estado.historialAhorros = [];
  estado.categoriaAbierta = null;
  estado.objetivos = [];
  estado.vistaObjetivo = null;
  estado.guardando = false;
  estado.errorObjetivo = null;
  estado.confirmandoBorrado = false;
  estado.email = "";
  estado.error = null;
}
