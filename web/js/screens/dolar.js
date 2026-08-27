// Panel "Análisis del dólar", dentro de Gastos.

import { esc, montosOcultos } from "../format.js";
import { analisis, CASAS, nombreDe, ultimos } from "../dolar.js";

const ANCHO = 560;
const ALTO = 150;
const MARGEN = 10;

function pesos(valor) {
  if (montosOcultos()) return "•••";
  return `$${valor.toLocaleString("es-AR", { maximumFractionDigits: 2 })}`;
}

function pct(valor) {
  if (montosOcultos()) return "••";
  const signo = valor > 0 ? "+" : "";
  return `${signo}${(valor * 100).toLocaleString("es-AR", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}%`;
}

function fechaCorta(iso) {
  const meses = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"];
  const [, m, d] = iso.split("-");
  return `${Number(d)} ${meses[Number(m) - 1]}`;
}

/** Línea de la serie. Propia y no `linea.js`: esa espera puntos con .acumulado. */
function grafico(puntos) {
  if (puntos.length < 2) {
    return `<p class="vacio">Todavía no hay suficientes días para el gráfico.</p>`;
  }

  const valores = puntos.map((p) => p.venta);
  const max = Math.max(...valores);
  const min = Math.min(...valores);
  const rango = max - min || 1;

  const coords = puntos.map((p, i) => ({
    x: MARGEN + (i * (ANCHO - MARGEN * 2)) / (puntos.length - 1),
    y: MARGEN + (ALTO - MARGEN * 2) * (1 - (p.venta - min) / rango),
  }));

  const trazo = coords.map((c, i) => `${i ? "L" : "M"}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const area = `${trazo} L${coords.at(-1).x.toFixed(1)} ${ALTO - MARGEN} L${coords[0].x.toFixed(1)} ${ALTO - MARGEN} Z`;

  return `
    <svg viewBox="0 0 ${ANCHO} ${ALTO}" class="dolar-linea" role="img"
         aria-label="Evolución, de ${pesos(valores[0])} a ${pesos(valores.at(-1))}">
      <path class="patrimonio-area" d="${area}"></path>
      <path class="patrimonio-trazo" d="${trazo}"></path>
      <circle class="patrimonio-punto" cx="${coords.at(-1).x.toFixed(1)}"
              cy="${coords.at(-1).y.toFixed(1)}" r="3.5"></circle>
    </svg>
    <p class="patrimonio-ejes">
      <span>${esc(fechaCorta(puntos[0].fecha))}</span>
      <span>${montosOcultos() ? "" : `mín ${pesos(min)} · máx ${pesos(max)}`}</span>
      <span>${esc(fechaCorta(puntos.at(-1).fecha))}</span>
    </p>`;
}

function textoAnalisis(a) {
  const partes = [];

  if (a.masSubio) {
    partes.push(`El que más subió fue el <strong>${esc(a.masSubio.nombre)}</strong>
                 (${pct(a.masSubio.variacion)}).`);
  }
  if (a.masBajo) {
    partes.push(`El que más bajó, el <strong>${esc(a.masBajo.nombre)}</strong>
                 (${pct(a.masBajo.variacion)}).`);
  }
  if (!a.masSubio && !a.masBajo) {
    partes.push("Ninguno se movió de forma significativa respecto de ayer.");
  } else {
    partes.push(`Subieron ${a.subieron}, bajaron ${a.bajaron} y
                 ${a.quietas} ${a.quietas === 1 ? "quedó" : "quedaron"} igual.`);
  }

  return partes.join(" ").replace(/\s+/g, " ");
}

export function renderDolar(contenedor, { datos, casaAbierta = "oficial", setCasa }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta dolar";

  if (!datos || (datos.error && !datos.cotizaciones.length)) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">💵 Análisis del dólar</h2>
      <p class="vacio">
        ${esc(datos?.error ?? "No pude traer las cotizaciones.")}<br>
        Es un servicio de terceros; el resto de la pantalla funciona igual.
      </p>`;
    contenedor.append(seccion);
    return;
  }

  const { cotizaciones, serie, error } = datos;
  const a = analisis(cotizaciones);
  const puntos = ultimos(serie, casaAbierta);

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">💵 Análisis del dólar</h2>

    ${a ? `
      <p class="dolar-analisis">${textoAnalisis(a)}</p>
      <div class="dolar-brechas">
        ${a.brechaBlue ? `
          <span class="dolar-brecha">
            <span class="etiqueta">Brecha blue</span>
            <strong>${pct(a.brechaBlue.valor)}</strong>
          </span>` : ""}
        ${a.brechaMep ? `
          <span class="dolar-brecha">
            <span class="etiqueta">Brecha MEP</span>
            <strong>${pct(a.brechaMep.valor)}</strong>
          </span>` : ""}
      </div>` : `
      <p class="apunte">
        Sin histórico no puedo comparar contra ayer ni calcular variaciones.
      </p>`}

    ${error ? `<p class="apunte dolar-aviso">${esc(error)}</p>` : ""}

    <ul class="dolar-tabla">
      ${cotizaciones.map((c) => `
        <li class="dolar-fila ${c.casa === casaAbierta ? "es-activo" : ""}">
          <button data-casa="${esc(c.casa)}" class="dolar-boton">
            <span class="dolar-nombre">${esc(c.nombre)}</span>
            <span class="dolar-precios">
              <span class="dolar-venta">${c.venta ? pesos(c.venta) : "—"}</span>
              <span class="dolar-compra">${c.compra ? `compra ${pesos(c.compra)}` : ""}</span>
            </span>
            <span class="dolar-var ${
              c.variacion === null ? "es-sin-dato"
                : c.variacion > 0 ? "es-baja" : c.variacion < 0 ? "es-suba" : ""
            }">${c.variacion === null ? "—" : pct(c.variacion)}</span>
          </button>
        </li>`).join("")}
    </ul>

    <h3 class="termo-subtitulo">
      ${esc(nombreDe(casaAbierta))} <span class="titulo-nota">· últimos ${puntos.length} días</span>
    </h3>
    <div class="dolar-grafico">${grafico(puntos)}</div>

    <p class="apunte termo-nota">
      Las de hoy salen de dolarapi y el histórico de datos públicos diarios
      desde 2011, así que el gráfico funciona desde el primer día.
    </p>`;

  contenedor.append(seccion);

  for (const boton of seccion.querySelectorAll("[data-casa]")) {
    boton.addEventListener("click", () => setCasa?.(boton.dataset.casa));
  }
}
