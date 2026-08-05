// Gráfico de dona en SVG puro, sin librerías.
//
// Decisiones que vienen de la guía de visualización:
// - 2px de separación entre gajos, del color de la superficie, para que dos
//   categorías contiguas nunca se toquen y se lean como una sola.
// - La leyenda siempre está y lleva el monto escrito: la identidad no puede
//   depender solo del color.
// - El texto usa los tokens de tinta, nunca el color de la serie.

import { esc, monto, montosOcultos, TOPE_CATEGORIAS } from "./format.js";

const RADIO = 70;
const GROSOR = 26;
const CIRCUNFERENCIA = 2 * Math.PI * RADIO;
const SEPARACION = 2; // en unidades del path, ≈2px

/**
 * Devuelve una referencia al token, no un color: así el gráfico cambia de tema
 * solo, sin volver a dibujarse.
 *
 * Los tonos nunca se ciclan —repetir el primero diría "esta categoría es la
 * misma que aquella"—: de la séptima en adelante va el gris de "otros".
 */
export function colorDeCategoria(indice) {
  return indice < TOPE_CATEGORIAS ? `var(--cat-${indice + 1})` : "var(--cat-otros)";
}

/**
 * Dibuja la dona y su leyenda.
 *
 * @param {HTMLElement} contenedor
 * @param {Array<{categoria, total, porcentaje}>} datos ya ordenados de mayor a menor
 * @param {{moneda: string, total: number, conLeyenda?: boolean}} opciones
 *   conLeyenda en false solo cuando abajo hay otra cosa que cumple ese papel
 *   —las barras de Gastos, con los mismos colores en el mismo orden—: la
 *   identidad nunca puede quedar solo en el color.
 */
export function renderDona(contenedor, datos, { moneda, total, conLeyenda = true }) {
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
      // El color va en style y no en el atributo stroke: los atributos de
      // presentación de SVG no resuelven var().
      const gajo = `
        <circle
          class="dona-gajo ${seleccionado === i ? "es-activo" : ""} ${seleccionado !== null && seleccionado !== i ? "es-tenue" : ""}"
          cx="100" cy="100" r="${RADIO}"
          style="stroke:${colorDeCategoria(i)}"
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
      ${conLeyenda ? `
        <ul class="leyenda">
          ${datos.map((d, i) => `
            <li class="leyenda-fila ${seleccionado === i ? "es-activo" : ""}" data-indice="${i}" tabindex="0">
              <span class="leyenda-punto" style="background:${colorDeCategoria(i)}"></span>
              <span class="leyenda-nombre">${esc(d.categoria)}</span>
              <span class="leyenda-monto">${monto(d.total, moneda)}</span>
              <span class="leyenda-pct">${d.porcentaje.toFixed(0)}%</span>
            </li>`).join("")}
        </ul>` : ""}`;

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
