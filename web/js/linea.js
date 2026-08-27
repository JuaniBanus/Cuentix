// Línea de evolución del gasto, en SVG puro.

import { dibujarTrazo, hayQueAnimar } from "./animar.js";
import { esc, fechaCorta, monto } from "./format.js";

const ANCHO = 320;
const ALTO = 128;
const ARRIBA = 14;
const ABAJO = 10;
const DERECHA = 7;

/** Convierte la serie en coordenadas del viewBox. */
function puntos(serie, maximo) {
  const util = ANCHO - DERECHA;
  const alto = ALTO - ARRIBA - ABAJO;

  return serie.map((p, i) => ({
    ...p,
    x: serie.length === 1 ? 0 : (i / (serie.length - 1)) * util,
    y: ARRIBA + alto - (maximo ? (p.acumulado / maximo) * alto : 0),
  }));
}

export function renderLinea(contenedor, serie, { moneda, periodo }) {
  if (!serie.length) {
    contenedor.innerHTML = `<p class="vacio">Todavía no empezó el período.</p>`;
    return;
  }

  const maximo = serie[serie.length - 1].acumulado;
  const coords = puntos(serie, maximo);
  let cursor = coords.length - 1;

  const trazo = coords.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const area = `${trazo} L${coords[coords.length - 1].x.toFixed(1)} ${ALTO - ABAJO} L${coords[0].x.toFixed(1)} ${ALTO - ABAJO} Z`;

  const grilla = [0, 0.5, 1]
    .map((f) => {
      const y = ARRIBA + (ALTO - ARRIBA - ABAJO) * f;
      return `<line class="linea-grilla" x1="0" y1="${y}" x2="${ANCHO}" y2="${y}"></line>`;
    })
    .join("");

  contenedor.innerHTML = `
    <p class="linea-lectura">
      <strong class="linea-valor"></strong>
      <span class="linea-detalle apunte"></span>
    </p>

    <svg viewBox="0 0 ${ANCHO} ${ALTO}" class="linea-svg" tabindex="0" role="img"
         aria-label="Gasto acumulado de ${esc(periodo.etiqueta)}: ${monto(maximo, moneda)}">
      ${grilla}
      <path class="linea-area" d="${area}"></path>
      <path class="linea-trazo" d="${trazo}"></path>
      <line class="linea-cruz" y1="${ARRIBA - 6}" y2="${ALTO - ABAJO}"></line>
      <circle class="linea-punto" r="4"></circle>
    </svg>

    <div class="linea-eje">
      <span>${fechaCorta(serie[0].fecha)}</span>
      <span>${fechaCorta(serie[serie.length - 1].fecha)}</span>
    </div>`;

  const svg = contenedor.querySelector(".linea-svg");
  const cruz = contenedor.querySelector(".linea-cruz");
  const punto = contenedor.querySelector(".linea-punto");
  const valor = contenedor.querySelector(".linea-valor");
  const detalle = contenedor.querySelector(".linea-detalle");

  function mostrar(indice) {
    cursor = Math.max(0, Math.min(coords.length - 1, indice));
    const p = coords[cursor];

    cruz.setAttribute("x1", p.x);
    cruz.setAttribute("x2", p.x);
    punto.setAttribute("cx", p.x);
    punto.setAttribute("cy", p.y);

    valor.textContent = monto(p.acumulado, moneda);
    detalle.textContent =
      `al ${fechaCorta(p.fecha)}` + (p.delDia ? ` · ese día ${monto(p.delDia, moneda)}` : "");
  }

  /** El día más cercano al dedo: nadie puede apuntarle a una línea de 2px. */
  function alPuntero(evento) {
    const caja = svg.getBoundingClientRect();
    const x = ((evento.clientX - caja.left) / caja.width) * ANCHO;
    let cerca = 0;
    for (let i = 1; i < coords.length; i++) {
      if (Math.abs(coords[i].x - x) < Math.abs(coords[cerca].x - x)) cerca = i;
    }
    mostrar(cerca);
  }

  svg.addEventListener("pointermove", alPuntero);
  svg.addEventListener("pointerdown", alPuntero);
  svg.addEventListener("pointerleave", () => mostrar(coords.length - 1));

  svg.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    mostrar(cursor + (e.key === "ArrowRight" ? 1 : -1));
  });

  mostrar(cursor);

  if (hayQueAnimar()) dibujarTrazo(contenedor.querySelector(".linea-trazo"));
}
