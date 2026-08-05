// Pantalla Inicio: balance del período, dona de gastos, ingresos/ahorro y
// los últimos movimientos.

import { porMoneda, totalPorTipo, totalesPorCategoria } from "../cuentas.js";
import { renderDona } from "../donut.js";
import { esc, monto } from "../format.js";
import { acotar, chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";

export function renderInicio(contenedor, { movimientos, moneda, monedas, setMoneda, periodo }) {
  const delPeriodo = porMoneda(movimientos)[moneda] ?? [];

  const ingresos = totalPorTipo(delPeriodo, "ingreso");
  const gastos = totalPorTipo(delPeriodo, "gasto");
  const ahorro = totalPorTipo(delPeriodo, "ahorro");
  const balance = ingresos - gastos;

  const categorias = acotar(totalesPorCategoria(delPeriodo, "gasto"));
  const recientes = movimientos.slice(0, 5);

  contenedor.innerHTML = `
    <section class="bloque">
      ${chipsMoneda({ monedas, moneda })}
      <p class="etiqueta">Balance de ${esc(periodo.etiqueta)}</p>
      <p class="cifra-heroe ${balance < 0 ? "es-negativo" : ""}">${monto(balance, moneda)}</p>
      <p class="apunte">${
        delPeriodo.length
          ? `${monto(ingresos, moneda)} de ingresos − ${monto(gastos, moneda)} de gastos`
          : "Sin movimientos en este período"
      }</p>
    </section>

    <section class="tarjeta" aria-labelledby="titulo-gastos">
      <h2 id="titulo-gastos" class="tarjeta-titulo">Gastos por categoría</h2>
      <div id="dona"></div>
    </section>

    <div class="grilla-2">
      <section class="tarjeta tarjeta-mini">
        <p class="etiqueta">Ingresos</p>
        <p class="cifra-media">${monto(ingresos, moneda)}</p>
      </section>
      <section class="tarjeta tarjeta-mini">
        <p class="etiqueta">Ahorrado</p>
        <p class="cifra-media">${monto(ahorro, moneda)}</p>
      </section>
    </div>

    <section class="bloque">
      <h2 class="tarjeta-titulo">Recientes</h2>
      ${recientes.length
        ? listaMovimientos(recientes)
        : `<p class="vacio">No hay movimientos en este período.<br>
             Cargalos desde Telegram y aparecen acá.</p>`}
    </section>`;

  const dona = contenedor.querySelector("#dona");
  if (categorias.length) {
    renderDona(dona, categorias, { moneda, total: gastos });
  } else {
    dona.innerHTML = `<p class="vacio">No hay gastos en este período 🌱</p>`;
  }

  engancharMonedas(contenedor, setMoneda);
}
