// Sección "Registro total de lo ahorrado", dentro de Ahorros.

import { esc, montosOcultos } from "../format.js";
import { registroAhorro } from "../patrimonio.js";

const SIMBOLOS = { ARS: "$", USD: "US$" };
const NOMBRE = { ARS: "pesos", USD: "dólares" };

function mesLindo(iso) {
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];
  const [a, m] = iso.split("-");
  return `${nombres[Number(m) - 1]} ${a.slice(2)}`;
}

/** El monto tal cual está guardado, sin pasar por el conversor de la app:
 *  acá cada cifra representa plata real ahorrada en ESA moneda. */
function cifra(valor, moneda) {
  if (montosOcultos()) return "••••••";
  const simbolo = SIMBOLOS[moneda] ?? `${moneda} `;
  const enteros = Math.round(valor).toLocaleString("es-AR");
  return `${simbolo}${enteros}`;
}

function nombreDe(moneda) {
  return NOMBRE[moneda] ?? moneda;
}

function filaMes({ mes, porMoneda }, monedas) {
  return `
    <li class="registro-fila">
      <span class="registro-mes">${esc(mesLindo(mes))}</span>
      <span class="registro-cifras">
        ${monedas.map((moneda) => `
          <span class="registro-cifra ${porMoneda[moneda] ? "" : "es-tenue"}">
            <span class="registro-monto">${porMoneda[moneda] ? cifra(porMoneda[moneda], moneda) : "—"}</span>
            <span class="registro-etiqueta">${esc(nombreDe(moneda))}</span>
          </span>`).join("")}
      </span>
    </li>`;
}

export function renderPatrimonio(contenedor, { ahorros }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta patrimonio";

  const { monedas, meses, totales } = registroAhorro(ahorros);

  if (!meses.length) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">📒 Registro total de lo ahorrado</h2>
      <p class="vacio">Todavía no tenés ahorros cargados.</p>`;
    contenedor.append(seccion);
    return;
  }

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">📒 Registro total de lo ahorrado</h2>

    <div class="registro-totales">
      ${monedas.map((moneda) => `
        <div>
          <p class="etiqueta">Total en ${esc(nombreDe(moneda))}</p>
          <p class="cifra-media">${cifra(totales[moneda] ?? 0, moneda)}</p>
        </div>`).join("")}
    </div>

    <ul class="registro-meses">
      ${meses.map((m) => filaMes(m, monedas)).join("")}
    </ul>

    <p class="apunte termo-nota">
      Cada mes muestra lo que se ahorró ese mes, en la moneda en la que se
      guardó — no es un acumulado ni una conversión: pesos son pesos y
      dólares son dólares.
    </p>`;

  contenedor.append(seccion);
}
