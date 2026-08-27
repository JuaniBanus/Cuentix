// El movimiento que el CSS no puede hacer solo.

import { monto } from "./format.js";

/** Si la persona pidió menos movimiento, no hay animación y punto. */
export function sinMovimiento() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}


let animandoEstePintado = false;

export function empezarPintado(conEntrada) {
  animandoEstePintado = conEntrada && !sinMovimiento();
}

export function terminarPintado() {
  animandoEstePintado = false;
}

/** Lo llaman los gráficos para saber si les toca dibujarse o aparecer y ya. */
export function hayQueAnimar() {
  return animandoEstePintado;
}


const DURACION = 650;

/** Frena rápido al final. Es la misma sensación que --curva en el CSS: los */
const suavizar = (t) => 1 - Math.pow(1 - t, 3);

/** Cuenta una cifra desde cero hasta su valor. */
export function contarHasta(nodo, valor, formatear) {
  const final = formatear(valor);

  if (sinMovimiento() || !Number.isFinite(valor) || !/\d/.test(final)) {
    nodo.textContent = final;
    return;
  }

  const arranque = performance.now();

  nodo.textContent = final;

  function cuadro(ahora) {
    const avance = Math.min((ahora - arranque) / DURACION, 1);
    nodo.textContent = avance === 1 ? final : formatear(valor * suavizar(avance));
    if (avance < 1) requestAnimationFrame(cuadro);
  }

  requestAnimationFrame(cuadro);
}

/** Cuenta todas las cifras marcadas de una pantalla. */
export function animarCifras(contenedor) {
  for (const nodo of contenedor.querySelectorAll("[data-contar]")) {
    const valor = Number(nodo.dataset.contar);
    const moneda = nodo.dataset.moneda || "ARS";
    const signo = nodo.dataset.signo === "si";
    contarHasta(nodo, valor, (v) => monto(v, moneda, { signo }));
  }
}


/** Dibuja un path de punta a punta. */
export function dibujarTrazo(trazo, duracion = 900) {
  if (!trazo || sinMovimiento()) return;

  let largo;
  try {
    largo = trazo.getTotalLength();
  } catch {
    return;
  }
  if (!Number.isFinite(largo) || largo === 0) return;

  trazo.style.strokeDasharray = String(largo);
  trazo.style.strokeDashoffset = String(largo);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      trazo.style.transition = `stroke-dashoffset ${duracion}ms var(--curva)`;
      trazo.style.strokeDashoffset = "0";
    });
  });
}

/** Suelta un valor recién en el cuadro siguiente, para que una transición CSS */
export function enElProximoCuadro(hacer) {
  requestAnimationFrame(() => requestAnimationFrame(hacer));
}
