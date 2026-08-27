// Sección "Patrimonio en dólares", dentro de Ahorros.

import { esc, monto, montosOcultos } from "../format.js";
import { calcular, variacion } from "../patrimonio.js";

const ANCHO = 320;
const ALTO = 120;
const MARGEN = 8;

function grafico(puntos, valorDe, formato) {
  const valores = puntos.map(valorDe);
  const max = Math.max(...valores);
  const min = Math.min(...valores);
  const rango = max - min || 1;

  const coords = puntos.map((p, i) => ({
    x: MARGEN + (i * (ANCHO - MARGEN * 2)) / Math.max(puntos.length - 1, 1),
    y: MARGEN + (ALTO - MARGEN * 2) * (1 - (valorDe(p) - min) / rango),
  }));

  const trazo = coords.map((c, i) => `${i ? "L" : "M"}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const area = `${trazo} L${coords.at(-1).x.toFixed(1)} ${ALTO - MARGEN} L${coords[0].x.toFixed(1)} ${ALTO - MARGEN} Z`;

  return `
    <svg viewBox="0 0 ${ANCHO} ${ALTO}" class="patrimonio-linea" role="img"
         aria-label="Evolución del patrimonio, de ${formato(valores[0])} a ${formato(valores.at(-1))}">
      <path class="patrimonio-area" d="${area}"></path>
      <path class="patrimonio-trazo" d="${trazo}"></path>
      <circle class="patrimonio-punto" cx="${coords.at(-1).x.toFixed(1)}" cy="${coords.at(-1).y.toFixed(1)}" r="3.5"></circle>
    </svg>
    <p class="patrimonio-ejes">
      <span>${esc(puntos[0].mes)}</span><span>${esc(puntos.at(-1).mes)}</span>
    </p>`;
}

function pct(valor) {
  if (montosOcultos()) return "••";
  const signo = valor > 0 ? "+" : "";
  return `${signo}${(valor * 100).toLocaleString("es-AR", {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  })}%`;
}

function mesLindo(iso) {
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];
  const [a, m] = iso.split("-");
  return `${nombres[Number(m) - 1]} ${a.slice(2)}`;
}

/** Formato de dólares sin pasar por el conversor de la app. */
function usd(valor) {
  if (montosOcultos()) return "••••••";
  return `US$${Math.round(valor).toLocaleString("es-AR")}`;
}

export function renderPatrimonio(contenedor, { ahorros, inversiones, moneda, serieDolar }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta patrimonio";

  const { puntos, hayDolar } = calcular(ahorros, inversiones, moneda, serieDolar);

  if (puntos.length < 2) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">💵 Tu patrimonio en dólares</h2>
      <p class="vacio">
        Necesito al menos dos meses con ahorros o inversiones cargados para
        dibujar la evolución.
      </p>`;
    contenedor.append(seccion);
    return;
  }

  const v = variacion(puntos);
  const ultimo = puntos[puntos.length - 1];

  let lectura = "";
  if (v?.enDolares !== null && v?.enDolares !== undefined) {
    if (v.enPesos > 0 && v.enDolares < 0) {
      lectura = `En pesos creció, pero medido en dólares bajó: la suba no
                 alcanzó a cubrir lo que se movió el tipo de cambio.`;
    } else if (v.enPesos > 0 && v.enDolares > 0) {
      lectura = "Creció en las dos monedas: ahorraste por encima del dólar.";
    } else if (v.enPesos < 0 && v.enDolares < 0) {
      lectura = "Bajó en las dos monedas.";
    } else {
      lectura = "En pesos bajó pero en dólares subió, por el movimiento del tipo de cambio.";
    }
  }

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">💵 Tu patrimonio en dólares</h2>

    <div class="grilla-2 patrimonio-cifras">
      <div>
        <p class="etiqueta">Hoy, en pesos</p>
        <p class="cifra-media">${monto(ultimo.pesos, moneda)}</p>
      </div>
      <div>
        <p class="etiqueta">Hoy, en dólares</p>
        <p class="cifra-media">${ultimo.usd !== null ? usd(ultimo.usd) : "—"}</p>
      </div>
    </div>

    ${v ? `
      <p class="apunte patrimonio-lectura">
        De ${mesLindo(v.desde)} a ${mesLindo(v.hasta)}:
        <strong class="${v.enPesos >= 0 ? "es-suba" : "es-baja"}">${pct(v.enPesos)} en pesos</strong>
        ${v.enDolares !== null
          ? ` · <strong class="${v.enDolares >= 0 ? "es-suba" : "es-baja"}">${pct(v.enDolares)} en dólares</strong>`
          : ""}
      </p>
      ${lectura ? `<p class="apunte">${esc(lectura.replace(/\s+/g, " ").trim())}</p>` : ""}
    ` : ""}

    <div id="linea-patrimonio" class="patrimonio-grafico"></div>

    <p class="apunte termo-nota">
      ${hayDolar
        ? `Cada mes está valuado al dólar oficial de ESE mes, no al de hoy.
           La serie sale de datos públicos diarios, así que los meses viejos
           tienen su cotización real.`
        : `No pude traer la cotización histórica, así que muestro solo los pesos.`}
      El patrimonio son tus ahorros más lo invertido a precio de compra; no
      incluye el saldo de tus cuentas.
    </p>`;

  contenedor.append(seccion);

  const nodo = seccion.querySelector("#linea-patrimonio");
  const conDolar = puntos.filter((p) => p.usd !== null);

  nodo.innerHTML =
    hayDolar && conDolar.length >= 2
      ? grafico(conDolar.map((p) => ({ ...p, mes: mesLindo(p.mes) })), (p) => p.usd, usd)
      : grafico(
          puntos.map((p) => ({ ...p, mes: mesLindo(p.mes) })),
          (p) => p.pesos,
          (x) => monto(x, moneda)
        );
}
