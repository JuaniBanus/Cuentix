// Medidor semicircular para el score de salud financiera.

import { enElProximoCuadro, hayQueAnimar } from "./animar.js";

const RADIO = 70;
const GROSOR = 12;
const ANCHO = RADIO * 2 + GROSOR;
const ALTO = RADIO + GROSOR;

const CX = ANCHO / 2;
const CY = ALTO - GROSOR / 2;

const ARCO = Math.PI * RADIO;

/** Dibuja el medidor. */
export function renderGauge(contenedor, { score, banda, clase, oculto = false }) {
  const proporcion = Math.max(0, Math.min(100, score)) / 100;
  const semicirculo = `M ${GROSOR / 2} ${CY} A ${RADIO} ${RADIO} 0 0 1 ${ANCHO - GROSOR / 2} ${CY}`;

  const anima = hayQueAnimar();
  const arcoInicial = anima ? 0 : proporcion * ARCO;

  contenedor.innerHTML = `
    <div class="gauge">
      <svg viewBox="0 0 ${ANCHO} ${ALTO}" class="gauge-svg" role="img"
           aria-label="${oculto ? "Score oculto" : `Score ${score} de 100: ${banda}`}">
        <path d="${semicirculo}" class="gauge-pista"
              fill="none" stroke-width="${GROSOR}" stroke-linecap="round"/>
        ${oculto ? "" : `
          <path d="${semicirculo}" class="gauge-relleno ${clase}"
                fill="none" stroke-width="${GROSOR}" stroke-linecap="round"
                stroke-dasharray="${arcoInicial} ${ARCO}"/>`}
      </svg>
      <div class="gauge-centro">
        <span class="gauge-numero ${clase}">${oculto ? "••" : score}</span>
        <span class="gauge-escala">de 100</span>
      </div>
    </div>
    <p class="gauge-banda ${clase}">${oculto ? "" : banda}</p>`;

  if (!anima || oculto) return;

  const arco = contenedor.querySelector(".gauge-relleno");
  const numero = contenedor.querySelector(".gauge-numero");

  enElProximoCuadro(() => {
    arco.setAttribute("stroke-dasharray", `${proporcion * ARCO} ${ARCO}`);
  });

  contarEntero(numero, score, 900);
}

/** Cuenta un entero pelado, al ritmo del arco que lo acompaña. */
function contarEntero(nodo, valor, duracion) {
  const arranque = performance.now();
  nodo.textContent = String(valor);

  function cuadro(ahora) {
    const avance = Math.min((ahora - arranque) / duracion, 1);
    const suave = 1 - Math.pow(1 - avance, 3);
    nodo.textContent = String(Math.round(valor * suave));
    if (avance < 1) requestAnimationFrame(cuadro);
  }
  requestAnimationFrame(cuadro);
}
