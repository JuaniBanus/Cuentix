// Pantalla Inicio: balance del período, dona de gastos, ingresos/ahorro y
// los últimos movimientos.

import { porMoneda, totalPorTipo, totalesPorCategoria } from "../cuentas.js";
import { renderDona } from "../donut.js";
import { esc, monto, montosOcultos } from "../format.js";
import { renderGauge } from "../gauge.js";
import { bandaDe, calcularSalud, explicar } from "../salud.js";
import { acotar, chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";

// --------------------------------------------------------------------------
// Salud financiera
// --------------------------------------------------------------------------
//
// Va en Inicio y no en Gastos porque el score mira toda la película —ingresos,
// ahorro, colchón y objetivos—, no solo lo que sale. En Gastos se leería como
// una nota sobre el gasto, que es apenas uno de sus cinco componentes.
//
// La tarjeta muestra el desglose completo por decisión, no por adorno: un
// número sobre la propia plata sin decir de dónde sale no se puede discutir ni
// corregir, y lo único que se puede hacer con él es creerlo.

const DISCLAIMER_SALUD = `
  <p class="insights-aviso">
    Orientativo: es un cálculo propio sobre los movimientos que cargaste, con
    una fórmula fija que podés ver acá arriba. No es asesoramiento financiero
    ni un puntaje crediticio, y no tiene en cuenta tu situación completa.
  </p>`;

function filaComponente(c, oculto) {
  return `
    <li class="salud-fila">
      <span class="salud-nombre">${esc(c.etiqueta)}</span>
      <span class="salud-riel">
        <span class="salud-relleno ${bandaDe(c.puntos).clase}" style="width:${c.puntos}%"></span>
      </span>
      <span class="salud-puntos">${oculto ? "••" : Math.round(c.puntos)}</span>
      <span class="salud-peso">peso ${Math.round(c.pesoEfectivo)}%</span>
      <span class="salud-detalle">${esc(oculto ? "" : c.detalle)}</span>
    </li>`;
}

function tarjetaSalud(ctx, salud) {
  const oculto = montosOcultos();

  if (salud.score === null) {
    return `
      <section class="tarjeta" aria-labelledby="titulo-salud">
        <h2 id="titulo-salud" class="tarjeta-titulo">Salud financiera</h2>
        <p class="vacio">Todavía no hay datos suficientes para calcularla.
        Cargá algunos movimientos y vuelve con un número.</p>
      </section>`;
  }

  const { sube, baja, falta } = explicar(salud);

  const explicacion = [
    baja.length
      ? `<p class="salud-parrafo"><strong>Lo que más lo baja:</strong> ${baja.map(esc).join(". ")}.</p>`
      : "",
    sube.length
      ? `<p class="salud-parrafo"><strong>Lo que lo sostiene:</strong> ${sube.map(esc).join(". ")}.</p>`
      : "",
    // Que un componente no se pueda calcular cambia el score, así que se dice.
    // Callarlo daría un número que parece completo sin serlo.
    falta.length
      ? `<p class="salud-parrafo salud-falta"><strong>Sin datos para:</strong>
           ${falta.map(esc).join("; ")}. Esos componentes quedan fuera del promedio.</p>`
      : "",
  ].join("");

  return `
    <section class="tarjeta" aria-labelledby="titulo-salud">
      <h2 id="titulo-salud" class="tarjeta-titulo">Salud financiera</h2>
      <div id="gauge-salud"></div>
      ${salud.parcial
        ? `<p class="salud-parcial">Parcial: se calculó con ${salud.componentes.length} de
             ${salud.componentes.length + salud.noAplican.length} componentes.</p>`
        : ""}
      <ul class="salud-desglose">
        ${salud.componentes.map((c) => filaComponente(c, oculto)).join("")}
      </ul>
      ${oculto ? "" : explicacion}
      ${DISCLAIMER_SALUD}
    </section>`;
}

export function renderInicio(contenedor, ctx) {
  const { movimientos, moneda, monedas, setMoneda, periodo } = ctx;
  const delPeriodo = porMoneda(movimientos)[moneda] ?? [];

  const ingresos = totalPorTipo(delPeriodo, "ingreso");
  const gastos = totalPorTipo(delPeriodo, "gasto");
  const ahorro = totalPorTipo(delPeriodo, "ahorro");
  const balance = ingresos - gastos;

  const categorias = acotar(totalesPorCategoria(delPeriodo, "gasto"));
  const recientes = movimientos.slice(0, 5);

  const salud = calcularSalud({
    movimientos,
    movimientosPrevios: ctx.movimientosPrevios ?? [],
    historialAhorros: ctx.historialAhorros ?? [],
    objetivos: ctx.objetivos ?? [],
    moneda,
  });

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

    ${tarjetaSalud(ctx, salud)}

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

  const medidor = contenedor.querySelector("#gauge-salud");
  if (medidor && salud.score !== null) {
    renderGauge(medidor, {
      score: salud.score,
      banda: salud.banda.nombre,
      clase: salud.banda.clase,
      oculto: montosOcultos(),
    });
  }

  const dona = contenedor.querySelector("#dona");
  if (categorias.length) {
    renderDona(dona, categorias, { moneda, total: gastos });
  } else {
    dona.innerHTML = `<p class="vacio">No hay gastos en este período 🌱</p>`;
  }

  engancharMonedas(contenedor, setMoneda);
}
