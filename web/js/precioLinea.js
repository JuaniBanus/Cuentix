// Gráfico de precio histórico de un activo.

import { fechaCorta, monto, montosOcultos } from "./format.js";

const ANCHO = 320;
const ALTO = 120;
const PAD_Y = 10;

/** "+13,5%" — con coma, como todos los números de la app. */
function pctLocal(valor) {
  const signo = valor > 0 ? "+" : "";
  return `${signo}${valor.toLocaleString("es-AR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}

/** Coordenadas de cada punto dentro del viewBox. */
function coordenadas(puntos) {
  const valores = puntos.map((p) => p.cierre);
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const rango = max - min || 1;
  const util = ALTO - PAD_Y * 2;

  return puntos.map((p, i) => ({
    ...p,
    x: puntos.length === 1 ? ANCHO / 2 : (i / (puntos.length - 1)) * ANCHO,
    y: PAD_Y + (1 - (p.cierre - min) / rango) * util,
  }));
}

export function renderPrecioLinea(contenedor, puntos, { moneda }) {
  if (!puntos?.length) {
    contenedor.innerHTML = `<p class="vacio">No hay histórico para este activo.</p>`;
    return;
  }

  const coords = coordenadas(puntos);
  const linea = coords.map((c, i) => `${i ? "L" : "M"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const area = `${linea} L ${coords[coords.length - 1].x.toFixed(1)} ${ALTO} L ${coords[0].x.toFixed(1)} ${ALTO} Z`;

  const primero = puntos[0].cierre;
  const ultimo = puntos[puntos.length - 1].cierre;
  const subio = ultimo >= primero;
  const variacion = primero ? ((ultimo - primero) / primero) * 100 : 0;
  const clase = subio ? "es-suba" : "es-baja";

  contenedor.innerHTML = `
    <div class="precio-grafico ${clase}">
      <div class="precio-cabecera">
        <span class="precio-actual" data-precio>${monto(ultimo, moneda)}</span>
        <span class="precio-var ${clase}" data-var>
          ${montosOcultos() ? "••" : pctLocal(variacion)}
          <span class="apunte-tenue" data-fecha>en ${puntos.length} ruedas</span>
        </span>
      </div>
      <svg viewBox="0 0 ${ANCHO} ${ALTO}" class="precio-svg" preserveAspectRatio="none"
           role="img" aria-label="Precio de los últimos ${puntos.length} días"
           tabindex="0">
        <path d="${area}" class="precio-area" />
        <path d="${linea}" class="precio-linea" fill="none" stroke-width="2"
              vector-effect="non-scaling-stroke" />
        <line class="precio-guia" y1="0" y2="${ALTO}" x1="0" x2="0" hidden />
        <circle class="precio-punto" r="3.5" cx="0" cy="0" hidden />
      </svg>
      <div class="precio-pie">
        <span>${fechaCorta(puntos[0].fecha)}</span>
        <span>${fechaCorta(puntos[puntos.length - 1].fecha)}</span>
      </div>
    </div>`;

  enganchar(contenedor, coords, moneda, { ultimo, variacion });
}

function enganchar(contenedor, coords, moneda, inicial) {
  const svg = contenedor.querySelector(".precio-svg");
  const guia = contenedor.querySelector(".precio-guia");
  const punto = contenedor.querySelector(".precio-punto");
  const etiquetaPrecio = contenedor.querySelector("[data-precio]");
  const etiquetaFecha = contenedor.querySelector("[data-fecha]");

  let seleccionado = null;

  function mostrar(indice) {
    if (indice === null) {
      seleccionado = null;
      guia.hidden = punto.hidden = true;
      etiquetaPrecio.textContent = monto(inicial.ultimo, moneda);
      etiquetaFecha.textContent = `en ${coords.length} ruedas`;
      return;
    }

    seleccionado = Math.max(0, Math.min(coords.length - 1, indice));
    const c = coords[seleccionado];
    guia.hidden = punto.hidden = false;
    guia.setAttribute("x1", c.x);
    guia.setAttribute("x2", c.x);
    punto.setAttribute("cx", c.x);
    punto.setAttribute("cy", c.y);
    etiquetaPrecio.textContent = monto(c.cierre, moneda);
    etiquetaFecha.textContent = fechaCorta(c.fecha);
  }

  /** De la posición del puntero al índice del punto más cercano. */
  function indiceDesde(clientX) {
    const caja = svg.getBoundingClientRect();
    const proporcion = (clientX - caja.left) / caja.width;
    return Math.round(proporcion * (coords.length - 1));
  }

  svg.addEventListener("pointermove", (e) => mostrar(indiceDesde(e.clientX)));
  svg.addEventListener("pointerleave", () => mostrar(null));
  svg.addEventListener("pointerdown", (e) => mostrar(indiceDesde(e.clientX)));

  svg.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") mostrar((seleccionado ?? coords.length - 1) + 1);
    else if (e.key === "ArrowLeft") mostrar((seleccionado ?? coords.length - 1) - 1);
    else if (e.key === "Escape") mostrar(null);
    else return;
    e.preventDefault();
  });
  svg.addEventListener("blur", () => mostrar(null));
}
