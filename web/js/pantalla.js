// Si hay ancho de escritorio o no.
//
// Vive en su propio módulo para que el umbral esté escrito UNA vez. Con la
// consulta repetida en cada pantalla, mover el corte obligaría a acordarse de
// todos los lugares, y el que se olvide queda desincronizado sin avisar.
//
// 768px es el mismo corte que usa el CSS para pasar de la barra inferior a la
// superior: es la línea que este proyecto ya trazó entre "teléfono" y "lo
// demás". Un iPad vertical entra como escritorio; si se quisiera dejarlo
// afuera, el número es 1024 y se cambia solo acá.

const CONSULTA = "(min-width: 768px)";

export const esEscritorio = () => window.matchMedia(CONSULTA).matches;

/**
 * Avisa cuando se cruza el umbral, no en cada píxel que se mueve.
 *
 * Hace falta porque los paneles de escritorio no se esconden con CSS: no se
 * dibujan. Sin esto, achicar la ventana los dejaría puestos y agrandarla no
 * los traería hasta la próxima navegación.
 */
export function alCambiarDeTamano(hacer) {
  window.matchMedia(CONSULTA).addEventListener("change", hacer);
}
