// Pantalla Inicio: balance del mes, dona de gastos, ingresos/ahorro y recientes.

import { porMoneda, totalPorTipo, totalesPorCategoria } from "../data.js";
import { colorDeCategoria, renderDona } from "../donut.js";
import { esc, fechaCorta, monto, nombreDelMes, TOPE_CATEGORIAS } from "../format.js";

/** Deja las 6 categorías más grandes y junta el resto en "otros". */
function acotar(categorias) {
  if (categorias.length <= TOPE_CATEGORIAS) return categorias;

  const visibles = categorias.slice(0, TOPE_CATEGORIAS);
  const resto = categorias.slice(TOPE_CATEGORIAS);
  return [
    ...visibles,
    {
      categoria: `otros (${resto.length})`,
      total: resto.reduce((t, c) => t + c.total, 0),
      porcentaje: resto.reduce((t, c) => t + c.porcentaje, 0),
    },
  ];
}

function filaMovimiento(m) {
  const esIngreso = m.tipo === "ingreso";
  const inicial = (m.categoria || "?").charAt(0).toUpperCase();
  return `
    <li class="movimiento">
      <span class="movimiento-avatar" aria-hidden="true">${esc(inicial)}</span>
      <span class="movimiento-texto">
        <span class="movimiento-titulo">${esc(m.descripcion || m.categoria)}</span>
        <span class="movimiento-sub">${esc(m.categoria)} · ${fechaCorta(m.fecha)}</span>
      </span>
      <span class="movimiento-monto ${esIngreso ? "es-ingreso" : ""}">
        ${monto(Number(m.monto), m.moneda, { signo: esIngreso })}
      </span>
    </li>`;
}

export function renderInicio(contenedor, movimientos, { moneda, setMoneda, monedas }) {
  const delMes = porMoneda(movimientos)[moneda] ?? [];

  const ingresos = totalPorTipo(delMes, "ingreso");
  const gastos = totalPorTipo(delMes, "gasto");
  const ahorro = totalPorTipo(delMes, "ahorro");
  const balance = ingresos - gastos;

  const categorias = acotar(totalesPorCategoria(delMes, "gasto"));
  const recientes = movimientos.slice(0, 5);

  const selectorMoneda = monedas.length > 1
    ? `<div class="chips" role="group" aria-label="Moneda">
         ${monedas.map((m) => `
           <button class="chip ${m === moneda ? "es-activo" : ""}" data-moneda="${m}">${m}</button>
         `).join("")}
       </div>`
    : "";

  contenedor.innerHTML = `
    <section class="bloque">
      ${selectorMoneda}
      <p class="etiqueta">Balance de ${nombreDelMes()}</p>
      <p class="cifra-heroe ${balance < 0 ? "es-negativo" : ""}">${monto(balance, moneda)}</p>
      <p class="apunte">${
        delMes.length
          ? `${monto(ingresos, moneda)} de ingresos − ${monto(gastos, moneda)} de gastos`
          : "Sin movimientos todavía"
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
        ? `<ul class="movimientos">${recientes.map(filaMovimiento).join("")}</ul>`
        : `<p class="vacio">Todavía no hay movimientos este mes.<br>
             Cargalos desde Telegram y aparecen acá.</p>`}
    </section>`;

  const dona = contenedor.querySelector("#dona");
  if (categorias.length) {
    renderDona(dona, categorias, { moneda, total: gastos });
  } else {
    dona.innerHTML = `<p class="vacio">Todavía no hay gastos este mes 🌱</p>`;
  }

  for (const boton of contenedor.querySelectorAll("[data-moneda]")) {
    boton.addEventListener("click", () => setMoneda(boton.dataset.moneda));
  }
}
