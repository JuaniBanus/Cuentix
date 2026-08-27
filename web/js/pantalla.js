// Si hay ancho de escritorio o no.

const CONSULTA = "(min-width: 768px)";

export const esEscritorio = () => window.matchMedia(CONSULTA).matches;

/** Avisa cuando se cruza el umbral, no en cada píxel que se mueve. */
export function alCambiarDeTamano(hacer) {
  window.matchMedia(CONSULTA).addEventListener("change", hacer);
}
