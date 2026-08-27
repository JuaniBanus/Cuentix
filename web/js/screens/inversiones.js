// Pantalla Inversiones: valor del portafolio, distribución y posiciones.

import { renderAviso } from "../aviso.js";
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

/** Calcula el estado de cada posición. */
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

/** Reparto porcentual por alguna clave, con TODO llevado a USD. */
function porPosicion(posiciones) {
  const filas = [];

  for (const p of posiciones) {
    const tasa = tasaAUSD(p.moneda);
    if (tasa === null) return null;
    filas.push({
      etiqueta: p.ticker || p.nombre,
      detalle: p.ticker ? p.nombre : ETIQUETA_TIPO[p.tipo] ?? p.tipo,
      valor: p.valorActual * tasa,
      propio: p.valorActual,
      moneda: p.moneda,
      gana: p.valuada ? p.ganancia >= 0 : null,
    });
  }

  const total = filas.reduce((t, f) => t + f.valor, 0);
  return filas
    .map((f) => ({ ...f, porcentaje: total ? (f.valor / total) * 100 : 0 }))
    .sort((a, b) => b.valor - a.valor);
}


function barrasPorPosicion(filas) {
  const tope = filas[0]?.porcentaje || 100;

  return filas
    .map((f) => {
      const tono = f.gana === null ? "es-neutra" : f.gana ? "es-suba" : "es-baja";
      const pct = f.porcentaje < 1 ? "<1%" : `${f.porcentaje.toFixed(0)}%`;
      return `
      <li class="peso ${tono}">
        <span class="peso-nombre" title="${esc(f.detalle)}">${esc(f.etiqueta)}</span>
        <span class="peso-riel">
          <span class="peso-relleno" style="width:${Math.max((f.porcentaje / tope) * 100, 1.5)}%"></span>
        </span>
        <span class="peso-pct">${pct}</span>
        <span class="peso-monto">${monto(f.propio, f.moneda)}</span>
      </li>`;
    })
    .join("");
}


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

  const marcaVieja =
    p.origen === "guardado"
      ? `<span class="posicion-sub posicion-vieja">último precio conocido · ${fechaDeMomento(p.desde)}</span>`
      : "";

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

/** Tarjeta del gráfico histórico del activo abierto. */
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

/** Las que ya se vendieron: costo de compra, sin valuar contra el mercado. */
function bloqueCerradas(cerradas, abierto) {
  const cabecera = `
    <div class="tarjeta-cabecera">
      <h2 class="tarjeta-titulo">Cerradas · ${cerradas.length}</h2>
      <button class="chip ${abierto ? "es-activo" : ""}" data-alternar-cerradas
              aria-expanded="${abierto}">${abierto ? "Ocultar" : "Ver historial"}</button>
    </div>`;

  if (!abierto) return `<section class="tarjeta">${cabecera}</section>`;

  const filas = cerradas
    .map((i) => {
      const costo = Number(i.cantidad) * Number(i.precio_compra);
      return `
      <li class="posicion es-cerrada">
        <span class="posicion-marca" aria-hidden="true">${esc(String(i.ticker ?? i.nombre ?? "").slice(0, 4))}</span>
        <span class="posicion-texto">
          <span class="posicion-titulo">${i.ticker ? esc(i.ticker) : esc(i.nombre)}</span>
          <span class="posicion-sub">
            ${cantidad(i.cantidad)} × ${monto(i.precio_compra, i.moneda)} ·
            ${i.ticker ? esc(i.nombre) : ETIQUETA_TIPO[i.tipo] ?? esc(i.tipo)}
          </span>
          <span class="posicion-sub posicion-fecha">
            ${fechaCorta(i.fecha_compra)}${i.cerrada_en ? ` → ${fechaCorta(i.cerrada_en)}` : ""}
          </span>
        </span>
        <span class="posicion-cifras">
          <span class="posicion-valor">${monto(costo, i.moneda)}</span>
          <span class="posicion-gp es-sin-dato">costo de compra</span>
        </span>
      </li>`;
    })
    .join("");

  return `
    <section class="tarjeta">
      ${cabecera}
      <p class="nota-precios">
        No se valúan contra el mercado ni entran en los totales: ya no son tuyas.
      </p>
      <ul class="posiciones">${filas}</ul>
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
    verCerradas, alternarCerradas,
  } = ctx;

  if (errorInversiones) {
    renderAviso(contenedor, {
      mensaje: errorInversiones.message,
      esDeConexion: errorInversiones.esDeConexion,
      onReintentar: recargarInversiones,
    });
    return;
  }

  if (!inversiones) {
    contenedor.innerHTML = esqueletoInversiones();
    return;
  }

  const activas = inversiones.filter((i) => i.activa);
  const cerradas = inversiones.filter((i) => !i.activa);

  if (inversiones.length && !activas.length && !verCerradas) {
    contenedor.innerHTML = `
      <p class="vacio">No tenés posiciones abiertas 🌱<br>
      Cerraste ${cerradas.length} ${cerradas.length === 1 ? "tenencia" : "tenencias"}.
      Decile al bot algo como «compré 10 CEDEARs de Apple a US$25» para empezar
      un portafolio nuevo.</p>
      <button class="boton boton-chico" data-ver-cerradas>Ver el historial de cerradas</button>`;
    const ver = contenedor.querySelector("[data-ver-cerradas]");
    if (ver) ver.addEventListener("click", () => alternarCerradas?.(true));
    return;
  }

  if (!inversiones.length) {
    contenedor.innerHTML = `
      <p class="vacio">Todavía no cargaste inversiones 🌱<br>
      Decile al bot algo como «compré 10 CEDEARs de Apple a US$25».</p>`;
    return;
  }

  const posiciones = evaluar(activas, precios, preciosMercado);

  const monedas = [...new Set(posiciones.map((p) => p.moneda))].sort();

  const resumen = monedas.map((m) => {
    const deLaMoneda = posiciones.filter((p) => p.moneda === m);
    const valoradas = deLaMoneda.filter((p) => p.valuada);
    return {
      moneda: m,
      valorActual: deLaMoneda.reduce((t, p) => t + p.valorActual, 0),
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
        Concentración del portafolio${monedas.length > 1 ? " <span class='titulo-nota'>· repartido en USD</span>" : ""}
      </h2>
      <div id="barras-tipo"></div>
    </section>

    ${monedas.length > 1 ? `
    <section class="tarjeta">
      <h2 class="tarjeta-titulo">
        Distribución por moneda <span class='titulo-nota'>· en USD</span>
      </h2>
      <div id="barras-moneda"></div>
    </section>` : ""}

    ${historico ? bloqueHistorico(historico) : ""}

    <section class="bloque">
      <h2 class="tarjeta-titulo">Posiciones abiertas · ${posiciones.length}</h2>
      <ul class="posiciones">${posiciones.map(filaPosicion).join("")}</ul>
    </section>

    ${cerradas.length ? bloqueCerradas(cerradas, !!verCerradas) : ""}`;

  const SIN_TASAS = `<p class="vacio">No pude traer las cotizaciones, y sin una
    moneda común el reparto porcentual no significaría nada.</p>`;

  const pesos = porPosicion(posiciones);
  const mayor = pesos?.[0];
  contenedor.querySelector("#barras-tipo").innerHTML = pesos
    ? `<ul class="pesos">${barrasPorPosicion(pesos)}</ul>` +
      (mayor && mayor.porcentaje >= 40
        ? `<p class="peso-aviso">${esc(mayor.etiqueta)} concentra el
           ${mayor.porcentaje.toFixed(0)}% del portafolio.</p>`
        : "")
    : SIN_TASAS;

  const nodoMoneda = contenedor.querySelector("#barras-moneda");
  const porMoneda = nodoMoneda && agrupar(posiciones, (p) => p.moneda);
  if (nodoMoneda) nodoMoneda.innerHTML = porMoneda
    ? `<ul class="barras">
        ${porMoneda
          .map((m, i) => `<li class="barra">${celdasDeBarra(m, i, "USD")}</li>`)
          .join("")}
      </ul>`
    : SIN_TASAS;

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

  const alternar = contenedor.querySelector("[data-alternar-cerradas]");
  if (alternar) alternar.addEventListener("click", () => alternarCerradas?.(!verCerradas));
}
