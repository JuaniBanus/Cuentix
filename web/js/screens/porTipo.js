// Gastos, Ahorros e Inversiones son la misma pantalla con otro tipo: total del

import { porMoneda, totalesPorCategoria, totalPorTipo } from "../cuentas.js";
import { esc, monto } from "../format.js";
import { acotar, celdasDeBarra, chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";

/** Una barra por categoría, de mayor a menor, con el monto escrito al lado. */
function barras(categorias, moneda) {
  return `
    <ul class="barras">
      ${categorias.map((c, i) => `
        <li class="barra">${celdasDeBarra(c, i, moneda)}</li>`).join("")}
    </ul>`;
}

export function pantallaPorTipo({ tipo, titulo, etiquetaTotal, vacio }) {
  return function render(contenedor, { movimientos, moneda, monedas, setMoneda, periodo }) {
    const deLaMoneda = porMoneda(movimientos)[moneda] ?? [];
    const delTipo = deLaMoneda.filter((m) => m.tipo === tipo);

    const total = totalPorTipo(deLaMoneda, tipo);
    const categorias = acotar(totalesPorCategoria(deLaMoneda, tipo));

    contenedor.innerHTML = `
      <section class="bloque">
        <h1 class="pantalla-titulo">${esc(titulo)}</h1>
        ${chipsMoneda({ monedas, moneda })}
        <p class="etiqueta">${esc(etiquetaTotal)} en ${esc(periodo.etiqueta)}</p>
        <p class="cifra-heroe">${monto(total, moneda)}</p>
        <p class="apunte">${
          delTipo.length
            ? `${delTipo.length} ${delTipo.length === 1 ? "movimiento" : "movimientos"}`
            : "Sin movimientos en este período"
        }</p>
      </section>

      ${categorias.length > 1 ? `
        <section class="tarjeta">
          <h2 class="tarjeta-titulo">Por categoría</h2>
          ${barras(categorias, moneda)}
        </section>` : ""}

      <section class="bloque">
        <h2 class="tarjeta-titulo">Detalle</h2>
        ${delTipo.length
          ? listaMovimientos(delTipo)
          : `<p class="vacio">${esc(vacio)}</p>`}
      </section>`;

    engancharMonedas(contenedor, setMoneda);
  };
}
