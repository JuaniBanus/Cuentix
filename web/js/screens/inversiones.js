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
import { esqueletoInversiones, esqueletoPrecio } from "../esqueleto.js";
import { esc, fechaCorta, monto, montosOcultos, tasaAUSD } from "../format.js";
import { mercadoDe, ultimoConocido, vaPorElProxy } from "../mercado.js";
import { tienePrecioDeMercado } from "../precios.js";
import { renderPrecioLinea } from "../precioLinea.js";
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
 * El precio sale de una de tres fuentes, en este orden:
 *
 *   1. CRIPTO -> CoinGecko, que la web consulta directo.
 *   2. RESTO  -> el proxy del bot, en el mercado que corresponde a la moneda
 *      de la tenencia. Una posición en pesos se valúa contra BYMA y una en
 *      dólares contra NASDAQ: AAPL existe en los dos y son activos distintos.
 *   3. Si ninguna respondió, el ÚLTIMO PRECIO CONOCIDO guardado localmente,
 *      marcado con su fecha.
 *
 * `valuada` dice si el valor actual sale de un precio real —de cualquiera de
 * las tres— o es el costo repetido. Solo lo valuado entra en la ganancia:
 * contar una posición sin precio como 0% de G/P afirmaría que no se movió.
 */
function evaluar(inversiones, precios, preciosMercado) {
  return inversiones.map((inv) => {
    const costo = inv.cantidad * inv.precio_compra;
    const ticker = String(inv.ticker ?? "").toUpperCase();
    const mercado = mercadoDe(inv);

    let precioActual = null;
    let origen = null;
    let desde = null;

    if (tienePrecioDeMercado(inv.tipo)) {
      const p = precios?.[ticker];
      if (Number.isFinite(p)) [precioActual, origen] = [p, "coingecko"];
    } else if (vaPorElProxy(inv.tipo) && ticker) {
      const p = preciosMercado?.[`${mercado}:${ticker}`];
      if (Number.isFinite(p?.precio)) [precioActual, origen] = [p.precio, "mercado"];
    }

    // Nada en vivo: se recurre a lo último que supimos, si lo supimos.
    if (precioActual === null && ticker) {
      const previo = ultimoConocido(ticker, mercado);
      if (previo) {
        precioActual = previo.precio;
        origen = "guardado";
        desde = previo.cuando;
      }
    }

    if (!Number.isFinite(precioActual)) {
      return {
        ...inv, costo, precioActual: null, valorActual: costo,
        ganancia: 0, valuada: false, origen: null, desde: null,
      };
    }

    const valorActual = inv.cantidad * precioActual;
    return {
      ...inv, costo, precioActual, valorActual,
      ganancia: valorActual - costo,
      valuada: true, origen, desde,
    };
  });
}

/** Reparto por sector, con lo que no lo tenga agrupado aparte. */
function porSector(posiciones) {
  // El sector lo guarda el bot cuando el mensaje lo menciona; el proxy de
  // precios no lo provee. Así que hay tenencias sin sector, y van juntas en un
  // grupo propio en vez de repartirse o desaparecer del total.
  return agrupar(posiciones, (p) => (p.sector || "").trim() || "Sin sector");
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
    : `<span class="posicion-gp es-sin-dato" title="Ningún proveedor cubre este activo y no tengo un precio anterior guardado. Se muestra el precio de compra.">
         sin cotización
       </span>`;

  // Un precio guardado no es el de ahora, y decirlo importa: es la diferencia
  // entre "vale esto" y "la última vez que pude mirar valía esto".
  const marcaVieja =
    p.origen === "guardado"
      ? `<span class="posicion-sub posicion-vieja">último precio conocido · ${fechaDeMomento(p.desde)}</span>`
      : "";

  // El histórico sale del proxy, así que solo se ofrece para lo que el proxy
  // cubre. La cripto queda afuera a propósito: su precio viene de CoinGecko,
  // que acá se consulta sin serie histórica. Un botón que lleva a un error es
  // peor que no tener botón.
  const graficable = Boolean(p.ticker) && vaPorElProxy(p.tipo);
  const etiqueta = `${p.ticker || p.nombre}, ver histórico`;

  return `
    <li class="posicion">
      <span class="posicion-marca" aria-hidden="true">${esc(String(p.ticker ?? p.nombre ?? "").slice(0, 4))}</span>
      <span class="posicion-texto">
        <span class="posicion-titulo">${identidad}</span>
        <span class="posicion-sub">
          ${cantidad(p.cantidad)} × ${monto(p.precio_compra, p.moneda)} · ${subtitulo}
        </span>
        <span class="posicion-sub posicion-fecha">${fechaCorta(p.fecha_compra)}</span>
        ${marcaVieja}
      </span>
      <span class="posicion-cifras">
        <span class="posicion-valor">${monto(p.valorActual, p.moneda)}</span>
        ${bloqueGP}
        ${graficable
          ? `<button class="posicion-grafico" data-historico="${esc(p.ticker)}"
                     data-mercado="${mercadoDe(p)}" aria-label="${esc(etiqueta)}">histórico</button>`
          : ""}
      </span>
    </li>`;
}

/**
 * Tarjeta del gráfico histórico del activo abierto.
 *
 * Vive en el estado y no adentro de la pantalla porque cada toque del ojo
 * redibuja todo, y una variable local se perdería con el gráfico abierto.
 */
function bloqueHistorico(historico) {
  const { ticker, cargando, error, puntos, moneda } = historico;

  let cuerpo;
  if (cargando) cuerpo = esqueletoPrecio();
  else if (error) cuerpo = `<p class="insights-error" role="alert">${esc(error)}</p>`;
  else cuerpo = `<div id="grafico-precio"></div>`;

  return `
    <section class="tarjeta" aria-labelledby="titulo-historico">
      <div class="tarjeta-cabecera">
        <h2 id="titulo-historico" class="tarjeta-titulo">${esc(ticker)} · últimos 90 días</h2>
        <button class="boton-icono" data-cerrar-historico aria-label="Cerrar el histórico">✕</button>
      </div>
      ${cuerpo}
    </section>`;
}

/** "hace 5 min" · "hace 3 h" · "el 4 ago". */
function fechaDeMomento(momento) {
  if (!momento) return "sin fecha";
  const minutos = Math.round((Date.now() - momento) / 60000);
  if (minutos < 1) return "recién";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  const fecha = new Date(momento);
  const iso = `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
  return `el ${fechaCorta(iso)}`;
}

export function renderInversiones(contenedor, ctx) {
  const {
    inversiones, errorInversiones, recargarInversiones,
    precios, errorPrecios, sinCotizar,
    preciosMercado, errorMercado, sinCoberturaMercado,
    historico, verHistorico,
  } = ctx;

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
  if (!inversiones) {
    contenedor.innerHTML = esqueletoInversiones();
    return;
  }

  if (!inversiones.length) {
    contenedor.innerHTML = `
      <p class="vacio">Todavía no cargaste inversiones 🌱<br>
      Decile al bot algo como «compré 10 CEDEARs de Apple a US$25».</p>`;
    return;
  }

  const posiciones = evaluar(inversiones, precios, preciosMercado);

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
  if (errorMercado) avisos.push(esc(errorMercado));
  if (sinCotizar?.length) {
    avisos.push(`Sin cotización en CoinGecko: ${esc(sinCotizar.join(", "))}`);
  }
  if (sinCoberturaMercado?.length) {
    avisos.push(`Sin cobertura del proveedor: ${esc(sinCoberturaMercado.join(", "))}`);
  }

  // Las que se muestran con un precio guardado se cuentan aparte de las que no
  // tienen precio: son situaciones distintas y la salida también.
  const conPrecioViejo = posiciones.filter((p) => p.origen === "guardado").length;
  if (conPrecioViejo) {
    avisos.push(
      `${conPrecioViejo} ${conPrecioViejo === 1 ? "posición" : "posiciones"} con el último ` +
        `precio conocido, no con el de ahora`
    );
  }

  const sinValuar = posiciones.filter((p) => !p.valuada).length;
  if (sinValuar) {
    avisos.push(
      `${sinValuar} ${sinValuar === 1 ? "posición" : "posiciones"} a precio de compra: ` +
        `ningún proveedor las cubre y no hay precio anterior guardado`
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
        <p class="cifra-heroe" data-contar="${r.valorActual}" data-moneda="${esc(r.moneda)}">${monto(r.valorActual, r.moneda)}</p>
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

    <section class="tarjeta">
      <h2 class="tarjeta-titulo">
        Distribución por sector<span class='titulo-nota'>· en USD</span>
      </h2>
      <div id="barras-sector"></div>
    </section>

    ${historico ? bloqueHistorico(historico) : ""}

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

  const sectores = porSector(posiciones);
  const nodoSector = contenedor.querySelector("#barras-sector");
  if (!sectores) {
    nodoSector.innerHTML = SIN_TASAS;
  } else if (sectores.length === 1 && sectores[0].categoria === "Sin sector") {
    // Repartir 100% en "Sin sector" no es una distribución, es un cartel raro.
    // Se dice qué falta y cómo se completa.
    nodoSector.innerHTML = `<p class="vacio">Ninguna tenencia tiene sector cargado.
      El proveedor de precios no lo informa, así que sale de lo que le contás al
      bot: «compré 10 CEDEARs de Apple a US$25, tecnología».</p>`;
  } else {
    nodoSector.innerHTML = `<ul class="barras">
        ${sectores.map((s, i) => `<li class="barra">${celdasDeBarra(s, i, "USD")}</li>`).join("")}
      </ul>`;
  }

  if (historico && !historico.cargando && !historico.error) {
    const nodo = contenedor.querySelector("#grafico-precio");
    if (nodo) renderPrecioLinea(nodo, historico.puntos ?? [], { moneda: historico.moneda });
  }

  for (const boton of contenedor.querySelectorAll("[data-historico]")) {
    boton.addEventListener("click", () =>
      verHistorico?.(boton.dataset.historico, boton.dataset.mercado)
    );
  }
  const cerrar = contenedor.querySelector("[data-cerrar-historico]");
  if (cerrar) cerrar.addEventListener("click", () => verHistorico?.(null));
}
