// Navegación por tabs.
//
// TABS es la fuente única: de esta lista salen los botones de la barra inferior
// y también la pantalla que se pinta. Agregar una sección es agregar una línea,
// no tocar el HTML y el JS por separado y esperar que queden sincronizados.

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

// `datos: true` marca las que no tienen nada que mostrar si la consulta falló.
// Usuario no lleva la marca a propósito: sin internet igual se tiene que poder
// cambiar el tema y cerrar sesión.
//
// `roles` dice quién ve cada sección. Un superusuario administra cuentas y no
// tiene finanzas —ni propias—, así que las cuatro secciones de plata no son
// suyas; un usuario común nunca ve administración.
//
// Esto es lo que se DIBUJA, y no hay que confundirlo con lo que se PUEDE. Que
// una sección no esté en la barra no impide pedirle los datos a Supabase con un
// curl: lo que lo impide son las policies restrictivas de migrations/014. Acá
// se decide qué app tiene sentido mostrar; allá, qué se puede leer.
export const TABS = [
  { id: "inicio", nombre: "Inicio", icono: "i-casa", render: renderInicio, datos: true,
    roles: ["usuario"] },
  { id: "gastos", nombre: "Gastos", icono: "i-gastos", render: renderGastos, datos: true,
    roles: ["usuario"] },
  { id: "ahorros", nombre: "Ahorros", icono: "i-ahorro", render: renderAhorros, datos: true,
    roles: ["usuario"] },
  // Sin `datos`: la cartera tiene su propia consulta y no sale de los
  // movimientos del período, así que un fallo de esos no la deja sin mostrar.
  { id: "inversiones", nombre: "Inversiones", icono: "i-inversion", render: renderInversiones,
    roles: ["usuario"] },
  // La única del superusuario. Sin `datos` porque su error se muestra adentro
  // de la pantalla, con el botón de reintentar al lado de la lista.
  { id: "admin", nombre: "Usuarios", icono: "i-usuario", render: renderAdmin,
    roles: ["superusuario"] },
  // `aparte` la saca de la fila del medio y la manda al extremo derecho de la
  // barra, junto al ojo, reducida al ícono. No es una vista de datos como las
  // otras cuatro: es la cuenta. La ven los dos roles: cerrar sesión y cambiar
  // el tema no dependen de qué tipo de cuenta tengas.
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

/** @param {{nav: HTMLElement, contenido: HTMLElement, acciones: object}} opciones */
export function montarNavegacion(opciones) {
  ({ nav, contenido, acciones } = opciones);
  // La barra NO se dibuja acá: todavía no se sabe el rol, y con la lista
  // completa se vería un instante la barra de finanzas antes de cambiarla por
  // la de administración. La dibuja `armarBarra`, ya con el perfil leído.
}

/**
 * Dibuja la barra con las secciones del rol y deja el tab activo en una válida.
 *
 * Se llama al entrar, cuando ya se sabe quién es. El reacomodo del tab importa:
 * `estado.tab` arranca en "inicio", que para un superusuario no existe, y sin
 * esto quedaría con una sección activa que no está en su barra.
 */
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
  // Hay pantallas con datos propios que no vienen en la carga inicial. Se
  // avisa acá y no en cada una para que sigan siendo funciones de pintado.
  acciones.alEntrarA?.(tab);
  estado.categoriaAbierta = null;
  estado.vistaObjetivo = null;
  estado.confirmandoBorrado = false;
  // Cambiar de sección arranca arriba: si venías scrolleado en Inicio, la
  // pantalla nueva empezaría por la mitad.
  window.scrollTo({ top: 0 });
  pintar(true);
}

/**
 * Redibuja la barra y la pantalla activa con el estado de ahora.
 *
 * @param {boolean} [conEntrada] true cuando el repintado es una navegación: se
 *   cambió de sección, se abrió una categoría, se entró a un objetivo. En esos
 *   casos la pantalla entra escalonada y los gráficos se dibujan solos.
 *
 *   Va en false —el valor por omisión— para todo lo demás: tocar el ojo, cambiar
 *   de moneda, la cotización que llega tarde. Ahí la persona está mirando un
 *   dato concreto y volver a animarlo se lo esconde medio segundo justo cuando
 *   lo está leyendo.
 */
export function pintar(conEntrada = false) {
  marcarActiva(nav, estado.tab);

  // Se busca SOLO entre las del rol, y el respaldo también sale de esa lista.
  // Con `TABS[0]` de respaldo, un superusuario cuyo tab quedara en un id
  // desconocido caería en Inicio y la pantalla intentaría dibujar movimientos
  // que la base no le va a dar nunca.
  const visibles = tabsVisibles(estado.perfil?.rol);
  const actual = visibles.find((t) => t.id === estado.tab) ?? visibles[0];
  if (!actual) return;

  // Marca de qué pantalla se está mostrando. No la usa el JS: es el gancho del
  // que cuelgan los reacomodos de dos columnas en pantalla grande, que si no no
  // tendrían cómo distinguir Inicio de Gastos.
  contenido.dataset.pantalla = actual.id;

  // La clase tiene que estar puesta ANTES de que se inserten las tarjetas: una
  // animación de entrada corre cuando el elemento aparece, no cuando la clase
  // llega después. Y `toggle` la saca sola en los repintados que no son
  // navegación, así que no hace falta limpiarla con un temporizador.
  contenido.classList.toggle("es-nueva", conEntrada);

  if (estado.error && actual.datos) {
    renderAviso(contenido, {
      mensaje: estado.error.message,
      esDeConexion: estado.error.esDeConexion,
      onReintentar: acciones.recargar,
    });
    return;
  }

  // Se avisa antes de pintar y se baja al terminar. Los gráficos lo consultan
  // mientras se dibujan —todo el pintado es sincrónico—, así que cada uno sabe
  // si le toca animarse sin que haya que pasarle un parámetro a través de las
  // cinco pantallas.
  empezarPintado(conEntrada);

  // La transición entre secciones. La clase se saca y se vuelve a poner en el
  // cuadro siguiente porque el navegador no reinicia una animación CSS si la
  // clase ya estaba: sin ese ida y vuelta, la segunda vez que entrás a una
  // pestaña no se anima nada.
  //
  // Solo al cambiar de sección (`conEntrada`), no en cada repintado: tocar el
  // ojo o cambiar de moneda redibuja la pantalla, y animarla entera en cada
  // toque sería mareante.
  if (conEntrada) {
    contenido.classList.remove("entrando");
    requestAnimationFrame(() => contenido.classList.add("entrando"));
  }

  // Todas las pantallas reciben el mismo contexto, así ninguna necesita
  // importar el estado ni saber cómo se recarga.
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
    // La fecha de hoy la pone el router y no cada pantalla: así todas las
    // secciones del mismo pintado usan la misma, y los tests la pueden fijar.
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
    insights: estado.insights,
    insightsCargando: estado.insightsCargando,
    insightsPedidos: estado.insightsPedidos,
    errorInsights: estado.errorInsights,
    analizarGastos: acciones.analizarGastos,
    categoriaAbierta: estado.categoriaAbierta,
    email: estado.email,
    perfil: estado.perfil,
    // Administración. Las pantallas de finanzas los ignoran; el panel es el
    // único que los usa.
    usuarios: estado.usuarios,
    errorAdmin: estado.errorAdmin,
    guardandoUsuario: estado.guardandoUsuario,
    cambiarEstadoUsuario: acciones.cambiarEstadoUsuario,
    recargarUsuarios: acciones.recargarUsuarios,
    setMoneda: (m) => {
      estado.moneda = m;
      // Cambiar de moneda cierra el detalle: la categoría abierta podría no
      // existir en la otra, y quedaría una pantalla de ceros.
      estado.categoriaAbierta = null;
      pintar();
    },
    // Abrir y cerrar el detalle de una categoría cambia la pantalla entera, así
    // que cuenta como navegación: entra escalonada, igual que cambiar de tab.
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

  // Va después del render porque necesita las cifras ya en el DOM.
  if (hayQueAnimar()) animarCifras(contenido);
  terminarPintado();
}
