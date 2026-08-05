// Pantalla Gastos: cuánto se fue en el período, contra el anterior, y en qué.
//
// Tiene dos vistas: el desglose por categoría y, al tocar una, su detalle. Cuál
// se ve sale de `categoriaAbierta`, que vive en el estado y no en una variable
// de acá: la pantalla se redibuja entera cada vez que se toca el ojo o se
// cambia de moneda, y una variable local se perdería en el camino.

import { porMoneda } from "../cuentas.js";
import { renderDona } from "../donut.js";
import { esc, monto } from "../format.js";
import { resumenDeGastos } from "../gastosCuentas.js";
import { renderLinea } from "../linea.js";
import { anterior } from "../periodo.js";
import { acotar, celdasDeBarra, chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";

// --------------------------------------------------------------------------
// Pedazos
// --------------------------------------------------------------------------

function lineaDeVariacion(resumen, periodo) {
  const etiquetaPrevia = esc(anterior(periodo).etiqueta);

  if (resumen.variacion === null) {
    return `<p class="apunte">Sin gastos en ${etiquetaPrevia} para comparar</p>`;
  }

  const subio = resumen.variacion > 0;
  const quieto = Math.abs(resumen.variacion) < 0.5;

  // Flecha en vez de color: gastar más no es "malo" ni gastar menos "bueno",
  // y pintar la cifra de rojo o verde lo daría por sentado.
  return `
    <p class="variacion">
      <span aria-hidden="true">${quieto ? "=" : subio ? "↑" : "↓"}</span>
      ${quieto ? "igual que" : `${Math.abs(resumen.variacion).toFixed(0)}% ${subio ? "más" : "menos"} que`}
      en ${etiquetaPrevia}
    </p>`;
}

function tarjetaDato(etiqueta, valor, apunte = "") {
  return `
    <section class="tarjeta tarjeta-mini">
      <p class="etiqueta">${esc(etiqueta)}</p>
      <p class="valor-texto">${valor}</p>
      ${apunte ? `<p class="apunte">${esc(apunte)}</p>` : ""}
    </section>`;
}

function datos(resumen, moneda) {
  const crecio = resumen.masCrecio;
  const detalleCrecio = crecio
    ? crecio.esNueva
      ? "no estaba antes"
      : `+${crecio.porcentaje.toFixed(0)}%`
    : "";

  return `
    <div class="grilla-2">
      ${tarjetaDato("Promedio diario", monto(resumen.diario, moneda))}
      ${tarjetaDato("Promedio mensual", monto(resumen.mensual, moneda), "a este ritmo")}
      ${tarjetaDato(
        "Más consume",
        resumen.masConsume ? esc(resumen.masConsume.categoria) : "—",
        resumen.masConsume ? `${resumen.masConsume.porcentaje.toFixed(0)}% del total` : ""
      )}
      ${tarjetaDato("Más creció", crecio ? esc(crecio.categoria) : "—", detalleCrecio)}
    </div>`;
}

/** Una barra por categoría, tocable, de mayor a menor. */
function barrasTocables(categorias, moneda) {
  return `
    <ul class="barras">
      ${categorias.map((c, i) => `
        <li>
          <button class="barra barra-tocable" data-categoria="${esc(c.categoria)}">
            ${celdasDeBarra(c, i, moneda)}
          </button>
        </li>`).join("")}
    </ul>`;
}

// --------------------------------------------------------------------------
// Las dos vistas
// --------------------------------------------------------------------------

function vistaDetalle(contenedor, { gastos, categoria, categorias, moneda, periodo, setCategoria }) {
  const dellaCategoria = gastos.filter((m) => m.categoria === categoria);
  const ficha = categorias.find((c) => c.categoria === categoria);
  const total = ficha?.total ?? 0;

  contenedor.innerHTML = `
    <section class="bloque">
      <button class="boton-volver">
        <svg viewBox="0 0 24 24" class="icono"><use href="#i-izquierda"></use></svg>
        Gastos
      </button>
      <h1 class="pantalla-titulo">${esc(categoria)}</h1>
      <p class="etiqueta">En ${esc(periodo.etiqueta)}</p>
      <p class="cifra-heroe">${monto(total, moneda)}</p>
      <p class="apunte">
        ${ficha ? `${ficha.porcentaje.toFixed(0)}% de todo lo gastado · ` : ""}
        ${dellaCategoria.length} ${dellaCategoria.length === 1 ? "movimiento" : "movimientos"}
      </p>
    </section>

    <section class="bloque">
      ${dellaCategoria.length
        ? listaMovimientos(dellaCategoria)
        : `<p class="vacio">No hay movimientos de esta categoría en el período.</p>`}
    </section>`;

  contenedor.querySelector(".boton-volver").addEventListener("click", () => setCategoria(null));
}

function vistaDesglose(contenedor, ctx, resumen) {
  const { moneda, monedas, periodo, setMoneda, setCategoria } = ctx;

  contenedor.innerHTML = `
    <section class="bloque">
      <h1 class="pantalla-titulo">Gastos</h1>
      ${chipsMoneda({ monedas, moneda })}
      <p class="etiqueta">Gastado en ${esc(periodo.etiqueta)}</p>
      <p class="cifra-heroe">${monto(resumen.total, moneda)}</p>
      ${lineaDeVariacion(resumen, periodo)}
    </section>

    ${resumen.categorias.length ? datos(resumen, moneda) : ""}

    <section class="tarjeta" aria-labelledby="titulo-evolucion">
      <h2 id="titulo-evolucion" class="tarjeta-titulo">Gasto acumulado</h2>
      <div id="grafico-linea"></div>
    </section>

    ${resumen.categorias.length ? `
      <section class="tarjeta" aria-labelledby="titulo-reparto">
        <h2 id="titulo-reparto" class="tarjeta-titulo">Reparto</h2>
        <div id="grafico-torta"></div>
      </section>` : ""}

    <section class="tarjeta" aria-labelledby="titulo-categorias">
      <h2 id="titulo-categorias" class="tarjeta-titulo">Por categoría</h2>
      ${resumen.categorias.length
        ? barrasTocables(resumen.categorias, moneda)
        : `<p class="vacio">No hay gastos en este período.</p>`}
    </section>`;

  renderLinea(contenedor.querySelector("#grafico-linea"), resumen.serie, { moneda, periodo });

  if (resumen.categorias.length) {
    // La torta recorta a seis y junta el resto: part-to-whole solo se lee de un
    // vistazo, y con quince gajos deja de leerse. Las barras de abajo, en
    // cambio, muestran todas.
    //
    // Va sin leyenda propia porque esas barras cumplen ese papel: mismos
    // colores, mismo orden, con el nombre y el monto escritos.
    renderDona(contenedor.querySelector("#grafico-torta"), acotar(resumen.categorias), {
      moneda,
      total: resumen.total,
      conLeyenda: false,
    });
  }

  engancharMonedas(contenedor, setMoneda);

  for (const boton of contenedor.querySelectorAll("[data-categoria]")) {
    boton.addEventListener("click", () => setCategoria(boton.dataset.categoria));
  }
}

// --------------------------------------------------------------------------

export function renderGastos(contenedor, ctx) {
  const { movimientos, movimientosPrevios, moneda, periodo, categoriaAbierta } = ctx;

  // Todo se mira dentro de una sola moneda: sumar pesos con dólares daría un
  // número que no existe.
  const deLaMoneda = porMoneda(movimientos)[moneda] ?? [];
  const previosDeLaMoneda = porMoneda(movimientosPrevios)[moneda] ?? [];

  const resumen = resumenDeGastos({
    movimientos: deLaMoneda,
    previos: previosDeLaMoneda,
    periodo,
  });

  if (categoriaAbierta) {
    vistaDetalle(contenedor, {
      gastos: deLaMoneda.filter((m) => m.tipo === "gasto"),
      categoria: categoriaAbierta,
      categorias: resumen.categorias,
      moneda,
      periodo,
      setCategoria: ctx.setCategoria,
    });
    return;
  }

  vistaDesglose(contenedor, ctx, resumen);
}
