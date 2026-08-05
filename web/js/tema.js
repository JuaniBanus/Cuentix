// Tema claro / oscuro.
//
// El tema es un atributo en <html> y nada más: todo el color sale de variables
// CSS, así que cambiarlo no obliga a redibujar ni una pantalla —ni la dona, que
// pinta sus gajos con var(--cat-N)—.

const CLAVE = "cuentix:tema";

/**
 * La barra del navegador en Android acompaña al fondo de la app. El color no se
 * escribe acá: se lee de --fondo, así el CSS sigue siendo el único lugar donde
 * un color de Cuentix está definido.
 */
function sincronizarBarra() {
  const fondo = getComputedStyle(document.documentElement)
    .getPropertyValue("--fondo")
    .trim();
  if (fondo) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", fondo);
}

export function temaActual() {
  return document.documentElement.dataset.tema === "claro" ? "claro" : "oscuro";
}

function temaDelSistema() {
  return matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "oscuro";
}

/** Lo elegido a mano, o null si nunca se tocó el interruptor. */
export function temaElegido() {
  try {
    const guardado = localStorage.getItem(CLAVE);
    return guardado === "claro" || guardado === "oscuro" ? guardado : null;
  } catch {
    // Modo incógnito o cookies bloqueadas: se puede vivir sin recordar la
    // preferencia, pero no se puede tirar la app abajo por eso.
    return null;
  }
}

export function aplicarTema(tema) {
  document.documentElement.dataset.tema = tema;
  sincronizarBarra();
}

export function alternarTema() {
  const nuevo = temaActual() === "claro" ? "oscuro" : "claro";
  aplicarTema(nuevo);
  try {
    localStorage.setItem(CLAVE, nuevo);
  } catch {
    // Igual que arriba: el tema vale para esta sesión y listo.
  }
  return nuevo;
}

/**
 * Mientras nadie haya elegido a mano, la app sigue al sistema en vivo: si el
 * teléfono pasa a modo claro de noche, la app acompaña. Después de tocar el
 * interruptor, manda lo elegido.
 */
export function seguirAlSistema() {
  // El script de index.html ya puso el atributo, pero corre antes de que exista
  // la hoja de estilos y no puede leer --fondo: la barra se pone al día acá.
  sincronizarBarra();

  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (!temaElegido()) aplicarTema(temaDelSistema());
  });
}
