// La narrativa mensual, al final de Inicio.

import { esc } from "../format.js";
import { nombreDelMes } from "../narrativa.js";

export function renderNarrativa(contenedor, ctx) {
  const { narrativas, mesCerrado, cargando, error, generar, verMes, mesAbierto } = ctx;

  const seccion = document.createElement("section");
  seccion.className = "tarjeta narrativa";

  const guardadas = narrativas ?? [];
  const abierta = mesAbierto
    ? guardadas.find((n) => n.mes === mesAbierto)
    : guardadas.find((n) => n.mes === mesCerrado) ?? guardadas[0];

  const otras = guardadas.filter((n) => n.mes !== abierta?.mes);

  if (cargando) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">✍️ Tu mes en palabras</h2>
      <p class="cargando">Escribiendo el resumen de ${esc(nombreDelMes(mesCerrado))}…</p>`;
    contenedor.append(seccion);
    return;
  }

  if (!abierta) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">✍️ Tu mes en palabras</h2>
      <p class="apunte">
        Puedo escribirte un resumen de cómo te fue en
        ${esc(nombreDelMes(mesCerrado))}, con tus números y comparado con tus
        propios meses anteriores.
      </p>
      ${error ? `<p class="error">${esc(error)}</p>` : ""}
      <button class="boton boton-acento" data-narrativa="generar">
        Escribir el resumen de ${esc(nombreDelMes(mesCerrado))}
      </button>`;
    contenedor.append(seccion);
    engancharNarrativa(seccion, { generar, verMes });
    return;
  }

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">✍️ Tu mes en palabras</h2>
    <p class="narrativa-mes">${esc(nombreDelMes(abierta.mes))}</p>
    <div class="narrativa-texto">
      ${abierta.texto.split(/\n{2,}/).map((p) => `<p>${esc(p.trim())}</p>`).join("")}
    </div>
    ${error ? `<p class="error">${esc(error)}</p>` : ""}

    ${!guardadas.some((n) => n.mes === mesCerrado) ? `
      <button class="boton" data-narrativa="generar">
        Escribir el de ${esc(nombreDelMes(mesCerrado))}
      </button>` : ""}

    ${otras.length ? `
      <details class="narrativa-anteriores">
        <summary>Meses anteriores (${otras.length})</summary>
        <ul class="narrativa-lista">
          ${otras.map((n) => `
            <li><button class="narrativa-link" data-narrativa-mes="${esc(n.mes)}">
              ${esc(nombreDelMes(n.mes))}
            </button></li>`).join("")}
        </ul>
      </details>` : ""}

    <p class="apunte termo-nota">
      Lo escribe una IA a partir de tus números —totales por categoría,
      variaciones contra tu propio promedio—, nunca del detalle de lo que
      escribiste al cargar cada gasto.
    </p>`;

  contenedor.append(seccion);
  engancharNarrativa(seccion, { generar, verMes });
}

function engancharNarrativa(seccion, { generar, verMes }) {
  const boton = seccion.querySelector("[data-narrativa='generar']");
  if (boton && generar) boton.addEventListener("click", () => generar());

  for (const link of seccion.querySelectorAll("[data-narrativa-mes]")) {
    link.addEventListener("click", () => verMes?.(link.dataset.narrativaMes));
  }
}
