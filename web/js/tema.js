// Tema claro / oscuro.

const CLAVE = "cuentix:tema";

/** La barra del navegador en Android acompaña al fondo de la app. El color no se */
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
  }
  return nuevo;
}

/** Mientras nadie haya elegido a mano, la app sigue al sistema en vivo: si el */
export function seguirAlSistema() {
  sincronizarBarra();

  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (!temaElegido()) aplicarTema(temaDelSistema());
  });
}
