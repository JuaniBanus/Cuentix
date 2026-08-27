// Gráfico de dona en SVG puro, sin librerías.

import { enElProximoCuadro, hayQueAnimar } from "./animar.js";
import { esc, monto, montosOcultos, TOPE_CATEGORIAS } from "./format.js";

const RADIO = 70;
const GROSOR = 26;
const CIRCUNFERENCIA = 2 * Math.PI * RADIO;
const SEPARACION = 2;

/** Devuelve una referencia al token, no un color: así el gráfico cambia de tema */
export function colorDeCategoria(indice) {
  return indice < TOPE_CATEGORIAS ? `var(--cat-${indice + 1})` : "var(--cat-otros)";
}

/** Dibuja la dona y su leyenda. */
export function renderDona(
  contenedor,
  datos,
  { moneda, total, conLeyenda = true, tituloTotal = "Gastado", unidad = ["categoría", "categorías"] }
) {
  let seleccionado = null;

  let primerDibujo = hayQueAnimar();

  function dibujar() {
    const centro = seleccionado === null
      ? {
          titulo: tituloTotal,
          valor: total,
          detalle: `${datos.length} ${datos.length === 1 ? unidad[0] : unidad[1]}`,
        }
      : {
          titulo: datos[seleccionado].categoria,
          valor: datos[seleccionado].total,
          detalle: `${datos[seleccionado].porcentaje.toFixed(0)}% del total`,
        };

    let offset = 0;
    const gajos = datos.map((d, i) => {
      const largo = (d.porcentaje / 100) * CIRCUNFERENCIA;
      const visible = datos.length === 1 ? largo : Math.max(largo - SEPARACION, 0.5);
      const guion = `${visible} ${CIRCUNFERENCIA - visible}`;
      const gajo = `
        <circle
          class="dona-gajo ${seleccionado === i ? "es-activo" : ""} ${seleccionado !== null && seleccionado !== i ? "es-tenue" : ""}"
          cx="100" cy="100" r="${RADIO}"
          style="stroke:${colorDeCategoria(i)}"
          stroke-width="${seleccionado === i ? GROSOR + 6 : GROSOR}"
          stroke-dasharray="${primerDibujo ? `0 ${CIRCUNFERENCIA}` : guion}"
          data-guion="${guion}"
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

    if (primerDibujo) {
      primerDibujo = false;
      const gajos = [...contenedor.querySelectorAll(".dona-gajo")];
      const ESCALON = 55;

      enElProximoCuadro(() => {
        gajos.forEach((gajo, i) => {
          gajo.style.transitionDelay = `${i * ESCALON}ms`;
          gajo.setAttribute("stroke-dasharray", gajo.dataset.guion);
        });
      });

      setTimeout(() => {
        for (const gajo of gajos) gajo.style.transitionDelay = "";
      }, gajos.length * ESCALON + 900);
    }

    for (const nodo of contenedor.querySelectorAll("[data-indice]")) {
      const indice = Number(nodo.dataset.indice);
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
