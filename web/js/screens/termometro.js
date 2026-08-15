// Termómetro de inflación personal, dentro de la pantalla de Gastos.
//
// Mira TODO el historial y no el período elegido, y lo dice: comparar precios
// necesita meses, y un selector de mes arriba haría pensar que el número se
// refiere a ese mes.
//
// La sección separa dos cosas que se confunden todo el tiempo:
//
//   PRECIOS  — servicios y compras con precio unitario. Acá "subió 30%"
//              significa que subió el precio. Es la inflación personal.
//   GASTO    — súper, comida, ropa. Acá "subió 30%" puede ser que compraste
//              más. Se muestra, pero NUNCA como inflación.
//
// Mezclarlas daría un número que parece serio y no lo es.

import { esc, monto, montosOcultos } from "../format.js";
import { calcular, gastoPorCategoria } from "../termometro.js";

const TOPE = 8;

function pct(valor, { signo = true } = {}) {
  if (montosOcultos()) return "••";
  const s = signo && valor > 0 ? "+" : "";
  return `${s}${(valor * 100).toLocaleString("es-AR", {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  })}%`;
}

function mesLindo(iso) {
  const [a, m] = iso.split("-");
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${nombres[Number(m) - 1]} ${a}`;
}

function filaItem(item, moneda) {
  const clase = item.variacion >= 0 ? "es-suba" : "es-baja";
  const unidad = item.unitario ? " por unidad" : "";
  return `
    <li class="termo-fila">
      <span class="termo-texto">
        <span class="termo-nombre">${esc(item.clave)}</span>
        <span class="termo-sub">
          ${monto(item.precioInicial, moneda)} → ${monto(item.precioFinal, moneda)}${unidad}
          · ${item.observaciones} compras
        </span>
      </span>
      <span class="termo-cifras">
        <span class="termo-var ${clase}">${pct(item.variacion)}</span>
        <span class="termo-tem">${pct(item.tem)}/mes</span>
      </span>
    </li>`;
}

/**
 * Dibuja la sección y la agrega al contenedor.
 *
 * @param {HTMLElement} contenedor
 * @param {{historial: Array, moneda: string, inflacionOficial: number|null}} ctx
 */
export function renderTermometro(contenedor, { historial, moneda, inflacionOficial = null }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta termo";

  const delaMoneda = (historial ?? []).filter((m) => m.moneda === moneda);
  const resultado = calcular(delaMoneda);
  const variables = gastoPorCategoria(delaMoneda);

  // Sin nada que medir, se explica QUÉ falta en vez de mostrar un cero.
  if (resultado.tem === null) {
    const pendientes = resultado.descartados.slice(0, 4);
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">🌡️ Tu inflación personal</h2>
      <p class="vacio">
        Todavía no puedo calcularla. Necesito el mismo ítem comprado en
        <strong>al menos dos meses distintos</strong>, y que sea algo cuyo total
        sea el precio (luz, internet, alquiler) o que me hayas dicho el precio
        por unidad («cargué 20 litros a $1.300»).
      </p>
      ${pendientes.length ? `
        <p class="apunte">Lo más cerca que estás:</p>
        <ul class="termo-pendientes">
          ${pendientes.map(([clave, motivo]) =>
            `<li><strong>${esc(clave)}</strong> — ${esc(motivo)}</li>`).join("")}
        </ul>` : ""}`;
    contenedor.append(seccion);
    return;
  }

  const comparacion = Number.isFinite(inflacionOficial)
    ? `<p class="apunte">
         El índice oficial viene a ${pct(inflacionOficial, { signo: false })} mensual.
         ${resultado.tem > inflacionOficial
            ? "Tu canasta sube más rápido."
            : "Tu canasta sube más despacio."}
       </p>`
    : "";

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">🌡️ Tu inflación personal</h2>
    <p class="cifra-media ${resultado.tem >= 0 ? "es-suba" : "es-baja"}">
      ${pct(resultado.tem)} por mes
    </p>
    <p class="apunte">
      Sobre ${resultado.items.length} ${resultado.items.length === 1 ? "ítem" : "ítems"}
      que pude seguir, de ${mesLindo(resultado.desde)} a ${mesLindo(resultado.hasta)}.
    </p>
    ${comparacion}

    <h3 class="termo-subtitulo">Lo que más aumentó</h3>
    <ul class="termo-lista">${resultado.items.slice(0, TOPE).map((i) => filaItem(i, moneda)).join("")}</ul>
    ${resultado.items.length > TOPE
      ? `<p class="apunte">…y ${resultado.items.length - TOPE} ítems más.</p>` : ""}

    ${variables.length ? `
      <h3 class="termo-subtitulo">Gasto por rubro <span class="titulo-nota">· no es precio</span></h3>
      <p class="apunte">
        Acá el total mezcla precio con cantidad: si el súper subió, puede ser
        que esté más caro o que hayas comprado más. Por eso no entra en el
        número de arriba.
      </p>
      <ul class="termo-lista">
        ${variables.slice(0, TOPE).map((v) => `
          <li class="termo-fila">
            <span class="termo-texto">
              <span class="termo-nombre">${esc(v.categoria)}</span>
              <span class="termo-sub">
                ${mesLindo(v.mesInicial)} → ${mesLindo(v.mesFinal)} ·
                ${monto(v.montoInicial, moneda)} → ${monto(v.montoFinal, moneda)}
              </span>
            </span>
            <span class="termo-cifras">
              <span class="termo-var ${v.variacion >= 0 ? "es-suba" : "es-baja"}">${pct(v.variacion)}</span>
            </span>
          </li>`).join("")}
      </ul>` : ""}

    <p class="apunte termo-nota">
      Es tu canasta, no el IPC: sale de los ítems que cargaste, en las fechas
      que los cargaste. Con pocos ítems un solo ajuste puede mover mucho el
      número.
    </p>`;

  contenedor.append(seccion);
}
