// Medidor semicircular para el score de salud financiera.
//
// Un semicírculo y no una dona entera: la dona dice "reparto de un total" y
// este número no es una parte de nada, es una posición en una escala de 0 a
// 100. Con la escala abierta a los costados se lee como un velocímetro, que es
// exactamente lo que es.
//
// El color sale de la banda y NUNCA es lo único que informa: el número está
// escrito en el centro y la banda en palabras abajo. Un score que solo se
// distinguiera por el color no lo podría leer alguien con daltonismo.

import { enElProximoCuadro, hayQueAnimar } from "./animar.js";

const RADIO = 70;
const GROSOR = 12;
// Ancho del viewBox: el radio a cada lado más el grosor del trazo, que se
// dibuja centrado sobre la línea y se saldría del recuadro sin este margen.
const ANCHO = RADIO * 2 + GROSOR;
const ALTO = RADIO + GROSOR;

const CX = ANCHO / 2;
const CY = ALTO - GROSOR / 2;

// Largo del arco de media circunferencia: es el 100% de la escala.
const ARCO = Math.PI * RADIO;

/**
 * Dibuja el medidor.
 *
 * @param {HTMLElement} contenedor
 * @param {object} opciones
 * @param {number} opciones.score  0 a 100
 * @param {string} opciones.banda  nombre de la banda, para el texto de abajo
 * @param {string} opciones.clase  clase CSS que define el color del arco
 * @param {boolean} opciones.oculto  con el ojo tapado se dibuja el arco vacío
 */
export function renderGauge(contenedor, { score, banda, clase, oculto = false }) {
  const proporcion = Math.max(0, Math.min(100, score)) / 100;
  const semicirculo = `M ${GROSOR / 2} ${CY} A ${RADIO} ${RADIO} 0 0 1 ${ANCHO - GROSOR / 2} ${CY}`;

  // El arco nace vacío y el valor entra un cuadro después: la transición del CSS
  // necesita un punto de partida distinto del de llegada, y un atributo escrito
  // de una sola vez no se lo da. La aguja barriendo la escala es, además, lo que
  // hace legible que esto es una posición en un rango y no un porcentaje.
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

  // El número acompaña al arco. Va con su propio contador y no con contarHasta()
  // porque no es plata: no lleva símbolo ni separador de miles, y pasarlo por
  // monto() lo escribiría como "$73".
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
