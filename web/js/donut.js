// Gráfico de dona en SVG puro, sin librerías.
//
// Decisiones que vienen de la guía de visualización:
// - 2px de separación entre gajos, del color de la superficie, para que dos
//   categorías contiguas nunca se toquen y se lean como una sola.
// - La leyenda siempre está y lleva el monto escrito: la identidad no puede
//   depender solo del color.
// - El texto usa los tokens de tinta, nunca el color de la serie.

import { COLOR_OTROS, COLORES, esc, monto, montosOcultos } from "./format.js";

const RADIO = 70;
const GROSOR = 26;
const CIRCUNFERENCIA = 2 * Math.PI * RADIO;
const SEPARACION = 2; // en unidades del path, ≈2px

export function colorDeCategoria(indice) {
  return indice < COLORES.length ? COLORES[indice] : COLOR_OTROS;
}

/**
 * Dibuja la dona y su leyenda.
 *
 * @param {HTMLElement} contenedor
 * @param {Array<{categoria, total, porcentaje}>} datos ya ordenados de mayor a menor
 * @param {{moneda: string, total: number}} opciones
 */
export function renderDona(contenedor, datos, { moneda, total }) {
  let seleccionado = null;

  function dibujar() {
    const centro = seleccionado === null
      ? { titulo: "Gastado", valor: total, detalle: `${datos.length} ${datos.length === 1 ? "categoría" : "categorías"}` }
      : {
          titulo: datos[seleccionado].categoria,
          valor: datos[seleccionado].total,
          detalle: `${datos[seleccionado].porcentaje.toFixed(0)}% del total`,
        };

    let offset = 0;
    const gajos = datos.map((d, i) => {
      const largo = (d.porcentaje / 100) * CIRCUNFERENCIA;
      // Con un solo gajo no hay vecino del que separarse, y restarle la
      // separación dejaría una muesca sin motivo.
      const visible = datos.length === 1 ? largo : Math.max(largo - SEPARACION, 0.5);
      const gajo = `
        <circle
          class="dona-gajo ${seleccionado === i ? "es-activo" : ""} ${seleccionado !== null && seleccionado !== i ? "es-tenue" : ""}"
          cx="100" cy="100" r="${RADIO}"
          stroke="${colorDeCategoria(i)}"
          stroke-width="${seleccionado === i ? GROSOR + 6 : GROSOR}"
          stroke-dasharray="${visible} ${CIRCUNFERENCIA - visible}"
          stroke-dashoffset="${-offset}"
          data-indice="${i}"
          tabindex="0"
          role="button"
          aria-label="${esc(d.categoria)}, ${d.porcentaje.toFixed(0)} por ciento"
        ></circle>`;
      offset += largo;
      return gajo;
    }).join("");

    contenedor.innerHTML = `
      <div class="dona-figura">
        <svg viewBox="0 0 200 200" class="dona" role="img"
             aria-label="Gastos por categoría del mes">
          <g transform="rotate(-90 100 100)">${gajos}</g>
        </svg>
        <div class="dona-centro">
          <span class="dona-centro-titulo">${esc(centro.titulo)}</span>
          <strong class="dona-centro-valor">${monto(centro.valor, moneda)}</strong>
          <span class="dona-centro-detalle">${montosOcultos() ? "" : esc(centro.detalle)}</span>
        </div>
      </div>
      <ul class="leyenda">
        ${datos.map((d, i) => `
          <li class="leyenda-fila ${seleccionado === i ? "es-activo" : ""}" data-indice="${i}" tabindex="0">
            <span class="leyenda-punto" style="background:${colorDeCategoria(i)}"></span>
            <span class="leyenda-nombre">${esc(d.categoria)}</span>
            <span class="leyenda-monto">${monto(d.total, moneda)}</span>
            <span class="leyenda-pct">${d.porcentaje.toFixed(0)}%</span>
          </li>`).join("")}
      </ul>`;

    for (const nodo of contenedor.querySelectorAll("[data-indice]")) {
      const indice = Number(nodo.dataset.indice);
      // Volver a tocar lo mismo deselecciona: sin esto no habría forma de
      // regresar al total sin recargar.
      const alternar = () => {
        seleccionado = seleccionado === indice ? null : indice;
        dibujar();
      };
      nodo.addEventListener("click", alternar);
      nodo.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          alternar();
        }
      });
    }
  }

  dibujar();
}
