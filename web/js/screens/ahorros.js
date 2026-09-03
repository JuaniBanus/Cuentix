// Pantalla Ahorros: cuánto se apartó, dónde quedó y cómo viene creciendo.

import { renderDolar } from "./dolar.js";
import { renderPatrimonio } from "./patrimonio.js";
import { renderRendimientos } from "./rendimientos.js";
import { renderRetos } from "./retos.js";
import { porMoneda, serieAcumulada, totalesPorCuenta, totalPorTipo } from "../cuentas.js";
import { colorDeCategoria } from "../donut.js";
import { cotizacionActual, esc, monto, montosOcultos, verEnDolares } from "../format.js";
import { renderLinea } from "../linea.js";
import { rango } from "../periodo.js";
import { chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";
import { engancharObjetivos, renderFormObjetivo, seccionObjetivos } from "./objetivos.js";

/** El equivalente en dólares del total, al oficial del día. */
function equivalenteEnDolares(total, moneda, { cotizacion, falloCotizacion }) {
  if (moneda !== "ARS" || verEnDolares()) return "";

  if (!cotizacion) {
    return falloCotizacion
      ? `<p class="apunte">No pude traer la cotización del dólar. Te muestro todo en pesos.</p>`
      : "";
  }

  const enDolares = total / cotizacion.venta;
  const cuando = new Date(cotizacion.fecha);
  const aviso = cotizacion.vencida
    ? ` · no pude actualizarla${
        Number.isNaN(cuando.getTime()) ? "" : `, es del ${cuando.toLocaleDateString("es-AR")}`
      }`
    : "";

  return `
    <p class="apunte">
      ≈ ${monto(enDolares, "USD")} al oficial
      ${montosOcultos() ? "" : `(${monto(cotizacion.venta, "ARS")})`}${aviso}
    </p>`;
}

/** Barras por lugar. Reusa los colores de categoría, en el mismo orden fijo. */
function barrasPorCuenta(lugares, moneda) {
  return `
    <ul class="barras">
      ${lugares.map((lugar, i) => `
        <li class="barra">
          <span class="barra-nombre ${lugar.sinDato ? "es-tenue" : ""}">${esc(lugar.cuenta)}</span>
          <span class="barra-monto">${monto(lugar.total, moneda)}</span>
          <span class="barra-riel">
            <span class="barra-relleno"
                  style="width:${Math.max(lugar.porcentaje, 1.5)}%;
                         background:${lugar.sinDato ? "var(--cat-otros)" : colorDeCategoria(i)}"></span>
          </span>
          <span class="barra-pct">${lugar.porcentaje.toFixed(0)}%</span>
        </li>`).join("")}
    </ul>`;
}

export function renderAhorros(contenedor, ctx) {
  const { movimientos, historialAhorros, moneda, monedas, periodo, setMoneda, objetivos } = ctx;
  const alFinal = () => {
    renderRetos(contenedor, { retos: ctx.retos, moneda, hoy: ctx.hoy });

    renderDolar(contenedor, {
      datos: ctx.dolar,
      casaAbierta: ctx.casaDolar,
      setCasa: ctx.setCasaDolar,
    });
    renderRendimientos(contenedor, { rendimientos: ctx.rendimientos ?? [], hoy: ctx.hoy });

    if (historialAhorros?.length) {
      renderPatrimonio(contenedor, { ahorros: historialAhorros });
    }
  };

  if (ctx.vistaObjetivo) {
    renderFormObjetivo(contenedor, ctx);
    return;
  }

  const delPeriodo = (porMoneda(movimientos)[moneda] ?? []).filter((m) => m.tipo === "ahorro");
  const total = totalPorTipo(porMoneda(movimientos)[moneda] ?? [], "ahorro");
  const lugares = totalesPorCuenta(porMoneda(movimientos)[moneda] ?? [], "ahorro");

  const historial = (porMoneda(historialAhorros)[moneda] ?? []).filter((m) => m.tipo === "ahorro");
  const acumulado = totalPorTipo(historial, "ahorro");

  const desdeElPrimero = historial.length
    ? rango(historial[historial.length - 1].fecha, historial[0].fecha)
    : null;

  contenedor.innerHTML = `
    <section class="bloque">
      <h1 class="pantalla-titulo">Ahorros</h1>
      ${chipsMoneda({ monedas, moneda })}
      <p class="etiqueta">Ahorrado en ${esc(periodo.etiqueta)}</p>
      <p class="cifra-heroe" data-contar="${total}" data-moneda="${esc(moneda)}">${monto(total, moneda)}</p>
      <p class="apunte">${
        delPeriodo.length
          ? `${delPeriodo.length} ${delPeriodo.length === 1 ? "movimiento" : "movimientos"}`
          : "No apartaste nada en este período"
      }</p>
      ${equivalenteEnDolares(total, moneda, ctx)}
    </section>

    ${seccionObjetivos(objetivos, historialAhorros)}

    ${lugares.length ? `
      <section class="tarjeta" aria-labelledby="titulo-lugares">
        <h2 id="titulo-lugares" class="tarjeta-titulo">Dónde quedó</h2>
        ${barrasPorCuenta(lugares, moneda)}
      </section>` : ""}

    ${historial.length ? `
      <section class="tarjeta" aria-labelledby="titulo-evolucion">
        <h2 id="titulo-evolucion" class="tarjeta-titulo">
          Evolución del ahorro <span class="apunte">· todo el historial</span>
        </h2>
        <div id="grafico-linea"></div>
        <p class="apunte tarjeta-pie">Llevás ${monto(acumulado, moneda)} ahorrados en total.</p>
      </section>` : ""}

    <section class="bloque bloque-detalle">
      <h2 class="tarjeta-titulo">Detalle de ${esc(periodo.etiqueta)}</h2>
      ${delPeriodo.length
        ? listaMovimientos(delPeriodo)
        : `<p class="vacio">No apartaste nada en este período.</p>`}
    </section>`;

  if (historial.length) {
    renderLinea(contenedor.querySelector("#grafico-linea"), serieAcumulada(historial, desdeElPrimero), {
      moneda,
      periodo: desdeElPrimero,
    });
  }

  engancharMonedas(contenedor, setMoneda);
  engancharObjetivos(contenedor, ctx);
  alFinal();
}
