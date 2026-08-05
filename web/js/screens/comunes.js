// Pedazos que usan varias pantallas. Están acá y no en la primera que los
// necesitó, para que Gastos no tenga que importar de Inicio.

import { colorDeCategoria } from "../donut.js";
import { esc, fechaCorta, monto, TOPE_CATEGORIAS } from "../format.js";

/** Selector de moneda. No aparece si solo hubo movimientos en una. */
export function chipsMoneda({ monedas, moneda }) {
  if (monedas.length <= 1) return "";
  return `
    <div class="chips" role="group" aria-label="Moneda">
      ${monedas.map((m) => `
        <button class="chip ${m === moneda ? "es-activo" : ""}" data-moneda="${m}">${m}</button>
      `).join("")}
    </div>`;
}

export function engancharMonedas(contenedor, setMoneda) {
  for (const boton of contenedor.querySelectorAll("[data-moneda]")) {
    boton.addEventListener("click", () => setMoneda(boton.dataset.moneda));
  }
}

/** Deja las 6 categorías más grandes y junta el resto en "otros". */
export function acotar(categorias) {
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

/**
 * Las cuatro celdas de una barra de categoría. Van aparte porque la barra se
 * usa suelta en Ahorros e Inversiones y adentro de un botón en Gastos, donde
 * abre el detalle: cambia el envoltorio, no el contenido.
 *
 * El ancho mínimo es 1.5% para que una categoría de $50 entre $500.000 se vea
 * como una línea fina y no como nada.
 */
export function celdasDeBarra(categoria, indice, moneda) {
  return `
    <span class="barra-nombre">${esc(categoria.categoria)}</span>
    <span class="barra-monto">${monto(categoria.total, moneda)}</span>
    <span class="barra-riel">
      <span class="barra-relleno"
            style="width:${Math.max(categoria.porcentaje, 1.5)}%; background:${colorDeCategoria(indice)}"></span>
    </span>
    <span class="barra-pct">${categoria.porcentaje.toFixed(0)}%</span>`;
}

export function filaMovimiento(m) {
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

export function listaMovimientos(movimientos) {
  return `<ul class="movimientos">${movimientos.map(filaMovimiento).join("")}</ul>`;
}
