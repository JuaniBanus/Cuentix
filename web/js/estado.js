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
  // Todos los gastos, sin acotar por período: el termómetro de inflación
  // compara precios entre meses y con el mes elegido no vería nada.
  historialGastos: [],
  // Serie histórica del dólar oficial, para valuar el patrimonio de cada mes
  // a la cotización de ESE mes. null = no llegó o no se pudo traer.
  serieDolar: null,

  // Narrativa mensual. `narrativas` son las ya guardadas; `mesAbierto` es cuál
  // se está leyendo (null = la del último mes cerrado).
  narrativas: [],
  narrativaCargando: false,
  errorNarrativa: null,
  mesAbierto: null,

  // Retos de ahorro. La web solo los muestra.
  retos: [],
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
  // Tenencias. No se acotan por período —son un stock, no movimientos— y se
  // traen recién al entrar al tab: quien no invierte no paga esa consulta.
  // null = todavía no se pidieron. [] = se pidieron y no hay ninguna.
  inversiones: null,
  // Si la consulta de tenencias falló, acá queda el ErrorAmable. Va aparte de
  // `error` porque las inversiones no dependen del período: que fallen los
  // movimientos no tiene por qué dejar la cartera sin mostrar, ni al revés.
  errorInversiones: null,
  // Precio de mercado por ticker, de CoinGecko. Solo la cripto tiene; el resto
  // se muestra a precio de compra y se dice en pantalla.
  precios: {},
  errorPrecios: null,
  // Tickers que CoinGecko no supo cotizar, para poder aclararlo.
  sinCotizar: [],
  // Precios de acciones, ETFs, CEDEARs y bonos, del proxy del bot. La clave
  // lleva el mercado adelante ("us:AAPL") porque el mismo ticker puede ser dos
  // activos distintos según dónde cotice.
  preciosMercado: {},
  errorMercado: null,
  sinCoberturaMercado: [],
  // Gráfico histórico abierto: {ticker, mercado, cargando, error, puntos, moneda}.
  // null = ninguno. Vive acá y no en la pantalla porque cada toque del ojo la
  // redibuja entera y una variable local se perdería.
  historico: null,
  // Panel de Insights de Gastos. El análisis se pide a mano, así que hace
  // falta recordar si ya se pidió: sin `insightsPedidos` no se distingue
  // "todavía no lo pediste" de "lo pedí y no había nada para decir".
  insights: [],
  insightsCargando: false,
  insightsPedidos: false,
  errorInsights: null,
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
  estado.historialGastos = [];
  estado.serieDolar = null;
  estado.narrativas = [];
  estado.narrativaCargando = false;
  estado.errorNarrativa = null;
  estado.mesAbierto = null;
  estado.retos = [];
  estado.inversiones = null;
  estado.errorInversiones = null;
  estado.precios = {};
  estado.errorPrecios = null;
  estado.sinCotizar = [];
  estado.preciosMercado = {};
  estado.errorMercado = null;
  estado.sinCoberturaMercado = [];
  estado.historico = null;
  estado.insights = [];
  estado.insightsCargando = false;
  estado.insightsPedidos = false;
  estado.errorInsights = null;
  estado.categoriaAbierta = null;
  estado.objetivos = [];
  estado.vistaObjetivo = null;
  estado.guardando = false;
  estado.errorObjetivo = null;
  estado.confirmandoBorrado = false;
  estado.email = "";
  estado.error = null;
}
