// Pantalla Inversiones: valor del portafolio, distribución y posiciones.
//
// Regla que ordena todo el archivo: si no hay precio de mercado, NO se inventa.
// Hoy solo la cripto tiene precio (CoinGecko). El resto se muestra valuado a
// su costo, marcado, y queda FUERA del cálculo de ganancia: meterlo con G/P
// cero diría "no ganaste ni perdiste", que es una afirmación falsa, no un dato
// ausente.
//
// A diferencia del resto de las pantallas, esta no mira el período: las
// tenencias son un stock. Una acción comprada hace dos años sigue en la cartera
// este mes, así que acotarla por fecha mostraría un portafolio vacío en cuanto
// no se compre nada.

import { renderAviso } from "../aviso.js";
import { renderDona } from "../donut.js";
import { esc, fechaCorta, monto, montosOcultos, tasaAUSD } from "../format.js";
import { tienePrecioDeMercado } from "../precios.js";
import { celdasDeBarra } from "./comunes.js";

const ETIQUETA_TIPO = {
  accion: "Acciones",
  etf: "ETF",
  bono: "Bonos",
  cedear: "CEDEARs",
  fci: "FCI",
  cripto: "Cripto",
  plazo_fijo: "Plazos fijos",
};

/** Número con un decimal y separadores locales, respetando el ojo. */
function pct(valor) {
  if (montosOcultos()) return "••";
  const signo = valor > 0 ? "+" : "";
  return `${signo}${valor.toLocaleString("es-AR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}

function cantidad(valor) {
  if (montosOcultos()) return "•••";
  return valor.toLocaleString("es-AR", { maximumFractionDigits: 8 });
}

/**
 * Calcula el estado de cada posición.
 *
 * Devuelve, por posición: costo, valor actual y G/P. `valuada` dice si el
 * valor actual sale de un precio de mercado real o es el costo repetido.
 */
function evaluar(inversiones, precios) {
  return inversiones.map((inv) => {
    const costo = inv.cantidad * inv.precio_compra;
    const precioActual = tienePrecioDeMercado(inv.tipo)
      ? precios?.[String(inv.ticker ?? "").toUpperCase()]
      : undefined;

    if (!Number.isFinite(precioActual)) {
      return { ...inv, costo, precioActual: null, valorActual: costo, ganancia: 0, valuada: false };
    }

    const valorActual = inv.cantidad * precioActual;
    return { ...inv, costo, precioActual, valorActual, ganancia: valorActual - costo, valuada: true };
  });
}

/**
 * Reparto porcentual por alguna clave, con TODO llevado a USD.
 *
 * La conversión no es un lujo acá: sumar 620.000 ARS con 32.582 USD como si
 * valieran lo mismo daría "95% en pesos", que no describe ninguna realidad.
 * Una distribución exige una unidad común; sin cotizaciones no se dibuja.
 *
 * @returns {Array<{categoria, total, porcentaje}>|null} null si falta alguna tasa.
 */
function agrupar(posiciones, clave) {
  const mapa = new Map();

  for (const p of posiciones) {
    const tasa = tasaAUSD(p.moneda);
    if (tasa === null) return null;
    const k = clave(p);
    mapa.set(k, (mapa.get(k) ?? 0) + p.valorActual * tasa);
  }

  const total = [...mapa.values()].reduce((t, v) => t + v, 0);
  return [...mapa.entries()]
    .map(([categoria, valor]) => ({
      categoria,
      total: valor,
      porcentaje: total ? (valor / total) * 100 : 0,
    }))
    .sort((a, b) => b.total - a.total);
}

function filaPosicion(p) {
  const signo = p.ganancia >= 0 ? "es-suba" : "es-baja";
  const identidad = p.ticker ? esc(p.ticker) : esc(p.nombre);
  const subtitulo = p.ticker ? esc(p.nombre) : ETIQUETA_TIPO[p.tipo] ?? esc(p.tipo);

  const bloqueGP = p.valuada
    ? `<span class="posicion-gp ${signo}">
         ${monto(p.ganancia, p.moneda, { signo: true })}
         <span class="posicion-pct">${pct(p.costo ? (p.ganancia / p.costo) * 100 : 0)}</span>
       </span>`
    : `<span class="posicion-gp es-sin-dato" title="Todavía no hay precio de mercado para acciones, CEDEARs, bonos y FCI. Por ahora se muestra el precio de compra.">
         sin precio aún
       </span>`;

  return `
    <li class="posicion">
      <span class="posicion-marca" aria-hidden="true">${esc(String(p.ticker ?? p.nombre ?? "").slice(0, 4))}</span>
      <span class="posicion-texto">
        <span class="posicion-titulo">${identidad}</span>
        <span class="posicion-sub">
          ${cantidad(p.cantidad)} × ${monto(p.precio_compra, p.moneda)} · ${subtitulo}
        </span>
        <span class="posicion-sub posicion-fecha">${fechaCorta(p.fecha_compra)}</span>
      </span>
      <span class="posicion-cifras">
        <span class="posicion-valor">${monto(p.valorActual, p.moneda)}</span>
        ${bloqueGP}
      </span>
    </li>`;
}

export function renderInversiones(contenedor, ctx) {
  const { inversiones, errorInversiones, recargarInversiones, precios, errorPrecios, sinCotizar } = ctx;

  // No pudimos leer la cartera: se dice, con el mismo aviso y botón de
  // reintentar que el resto de la app. Una lista vacía acá afirmaría que no
  // hay tenencias, que es distinto de no haberlas podido leer.
  if (errorInversiones) {
    renderAviso(contenedor, {
      mensaje: errorInversiones.message,
      esDeConexion: errorInversiones.esDeConexion,
      onReintentar: recargarInversiones,
    });
    return;
  }

  // null = todavía no llegó la consulta. [] = llegó y no hay tenencias. Sin la
  // distinción, la primera pintada diría "no cargaste nada" antes de saberlo.
  if (inversiones === null) {
    contenedor.innerHTML = `<p class="vacio">Cargando tus inversiones…</p>`;
    return;
  }

  if (!inversiones.length) {
    contenedor.innerHTML = `
      <p class="vacio">Todavía no cargaste inversiones 🌱<br>
      Decile al bot algo como «compré 10 CEDEARs de Apple a US$25».</p>`;
    return;
  }

  const posiciones = evaluar(inversiones, precios);

  // Los totales van por moneda: una cartera en USD y otra en ARS no se suman,
  // igual que en el resto de la app.
  const monedas = [...new Set(posiciones.map((p) => p.moneda))].sort();

  const resumen = monedas.map((m) => {
    const deLaMoneda = posiciones.filter((p) => p.moneda === m);
    const valoradas = deLaMoneda.filter((p) => p.valuada);
    return {
      moneda: m,
      valorActual: deLaMoneda.reduce((t, p) => t + p.valorActual, 0),
      // La ganancia se calcula SOLO sobre lo que tiene precio real. El % usa
      // ese mismo costo como base, no el de toda la cartera: si no, un 10% de
      // suba en la única cripto se diluiría contra acciones sin valuar.
      costoValorado: valoradas.reduce((t, p) => t + p.costo, 0),
      ganancia: valoradas.reduce((t, p) => t + p.ganancia, 0),
      cuantasValoradas: valoradas.length,
      total: deLaMoneda.length,
    };
  });

  const avisos = [];
  if (errorPrecios) avisos.push(esc(errorPrecios));
  if (sinCotizar?.length) {
    avisos.push(`Sin cotización en CoinGecko: ${esc(sinCotizar.join(", "))}`);
  }
  const sinValuar = posiciones.filter((p) => !p.valuada).length;
  if (sinValuar) {
    avisos.push(
      `${sinValuar} ${sinValuar === 1 ? "posición" : "posiciones"} a precio de compra ` +
        `(acciones, CEDEARs, bonos y FCI todavía no tienen precio de mercado)`
    );
  }

  contenedor.innerHTML = `
    ${resumen
      .map(
        (r) => `
      <section class="bloque">
        <p class="etiqueta">
          Valor del portafolio${monedas.length > 1 ? ` · ${esc(r.moneda)}` : ""}
        </p>
        <p class="cifra-heroe">${monto(r.valorActual, r.moneda)}</p>
        ${
          r.cuantasValoradas
            ? `<p class="apunte ${r.ganancia >= 0 ? "es-suba" : "es-baja"}">
                 ${monto(r.ganancia, r.moneda, { signo: true })} ·
                 ${pct(r.costoValorado ? (r.ganancia / r.costoValorado) * 100 : 0)}
                 <span class="apunte-tenue">sobre ${r.cuantasValoradas} de ${r.total} con precio de mercado</span>
               </p>`
            : `<p class="apunte">Ganancia no calculable: ninguna posición tiene precio de mercado todavía.</p>`
        }
      </section>`
      )
      .join("")}

    ${avisos.length ? `<p class="nota-precios">${avisos.join("<br>")}</p>` : ""}

    <section class="tarjeta">
      <h2 class="tarjeta-titulo">
        Distribución por tipo${monedas.length > 1 ? " <span class='titulo-nota'>· en USD</span>" : ""}
      </h2>
      <div id="dona-tipo"></div>
    </section>

    <section class="tarjeta">
      <h2 class="tarjeta-titulo">
        Distribución por moneda${monedas.length > 1 ? " <span class='titulo-nota'>· en USD</span>" : ""}
      </h2>
      <div id="barras-moneda"></div>
    </section>

    <section class="bloque">
      <h2 class="tarjeta-titulo">Posiciones</h2>
      <ul class="posiciones">${posiciones.map(filaPosicion).join("")}</ul>
    </section>`;

  const SIN_TASAS = `<p class="vacio">No pude traer las cotizaciones, y sin una
    moneda común el reparto porcentual no significaría nada.</p>`;

  // La dona ya sabe repartir colores, mostrar leyenda y respetar el ojo:
  // reusarla mantiene idéntico el lenguaje visual con la pantalla de Inicio.
  const porTipo = agrupar(posiciones, (p) => ETIQUETA_TIPO[p.tipo] ?? p.tipo);
  const nodoDona = contenedor.querySelector("#dona-tipo");
  if (porTipo) {
    renderDona(nodoDona, porTipo, {
      moneda: "USD",
      total: porTipo.reduce((t, c) => t + c.total, 0),
      tituloTotal: "Portafolio",
      unidad: ["tipo", "tipos"],
    });
  } else {
    nodoDona.innerHTML = SIN_TASAS;
  }

  // Por moneda va en barras y no en otra dona: son dos o tres categorías y
  // una segunda dona en la misma pantalla se lee como si midiera lo mismo.
  //
  // Usa `celdasDeBarra`, la misma que Gastos y Ahorros: la barra por moneda no
  // tiene por qué verse distinta de las demás por estar en otra pantalla.
  const porMoneda = agrupar(posiciones, (p) => p.moneda);
  contenedor.querySelector("#barras-moneda").innerHTML = porMoneda
    ? `<ul class="barras">
        ${porMoneda
          .map((m, i) => `<li class="barra">${celdasDeBarra(m, i, "USD")}</li>`)
          .join("")}
      </ul>`
    : SIN_TASAS;
}
