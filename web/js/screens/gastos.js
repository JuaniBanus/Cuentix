// Pantalla Gastos: cuánto se fue en el período, contra el anterior, y en qué.
//
// Tiene dos vistas: el desglose por categoría y, al tocar una, su detalle. Cuál
// se ve sale de `categoriaAbierta`, que vive en el estado y no en una variable
// de acá: la pantalla se redibuja entera cada vez que se toca el ojo o se
// cambia de moneda, y una variable local se perdería en el camino.

import { porMoneda } from "../cuentas.js";
import { renderDona } from "../donut.js";
import { esqueletoInsights } from "../esqueleto.js";
import { enmascararMontos, esc, monto, montosOcultos } from "../format.js";
import { resumenDeGastos } from "../gastosCuentas.js";
import { renderLinea } from "../linea.js";
import { anterior } from "../periodo.js";
import { acotar, celdasDeBarra, chipsMoneda, engancharMonedas, listaMovimientos } from "./comunes.js";
import { renderComparacion, renderRecurrentes } from "./recurrentes.js";
import { renderTermometro } from "./termometro.js";

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
      <p class="cifra-heroe" data-contar="${total}" data-moneda="${esc(moneda)}">${monto(total, moneda)}</p>
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

// --------------------------------------------------------------------------
// Panel de Insights
// --------------------------------------------------------------------------
//
// El análisis no se dispara solo al entrar a Gastos: lo pide la persona con el
// botón. Son dos razones distintas y las dos pesan. Una, cada análisis es una
// llamada a Gemini y no tiene sentido pagarla cada vez que alguien mira sus
// gastos de paso. La otra, el backend duerme cuando no tiene tráfico y puede
// tardar en despertar; una espera larga que empieza sin que nadie la pida se
// siente como que la app se colgó.

const ICONO_INSIGHT = {
  ahorro: "💡",
  crecimiento: "📈",
  suscripcion: "🔁",
  consejo: "🧭",
};

// Va SIEMPRE que se muestren insights, no escondido detrás de un "ver más":
// son observaciones generadas por un modelo sobre los propios números, no una
// recomendación profesional, y eso tiene que estar a la vista de quien lee.
const DISCLAIMER = `
  <p class="insights-aviso">
    Orientativo: son observaciones automáticas sobre tus propios números,
    generadas con IA. No son asesoramiento financiero ni recomendaciones de
    inversión, y pueden tener errores. Revisalas antes de tomar decisiones.
  </p>`;

function tarjetaInsight(insight) {
  const icono = ICONO_INSIGHT[insight.tipo] ?? "•";
  // El texto lo escribe un modelo y trae las cifras adentro, así que el ojo
  // tiene que taparlas acá: no pasaron por monto() como el resto de la app.
  const tapar = (t) => esc(montosOcultos() ? enmascararMontos(t) : t);
  return `
    <li class="insight">
      <span class="insight-icono" aria-hidden="true">${icono}</span>
      <span class="insight-texto">
        <span class="insight-titulo">${tapar(insight.titulo)}</span>
        <span class="insight-detalle">${tapar(insight.detalle)}</span>
        ${insight.referencia ? `<span class="insight-ref">${esc(insight.referencia)}</span>` : ""}
      </span>
    </li>`;
}

function panelInsights(ctx) {
  const { insights, insightsCargando, errorInsights, insightsPedidos } = ctx;

  let cuerpo;

  if (insightsCargando) {
    cuerpo = esqueletoInsights();
  } else if (errorInsights) {
    cuerpo = `
      <p class="insights-error" role="alert">${esc(errorInsights)}</p>
      <button class="boton" data-insights>Reintentar</button>`;
  } else if (insights?.length) {
    cuerpo = `<ul class="insights">${insights.map(tarjetaInsight).join("")}</ul>
      ${DISCLAIMER}
      <button class="boton boton-tenue" data-insights>Volver a analizar</button>`;
  } else if (insightsPedidos) {
    // Pedido, respondido y sin nada que decir. Es un resultado válido: con
    // pocos datos, inventar cinco observaciones sería peor que no dar ninguna.
    cuerpo = `
      <p class="vacio">No encontré nada que valga la pena señalar todavía.
      Con unos meses más de movimientos el análisis tiene más con qué trabajar.</p>
      ${DISCLAIMER}
      <button class="boton boton-tenue" data-insights>Volver a analizar</button>`;
  } else {
    cuerpo = `
      <p class="apunte">Miro tus últimos meses y te digo dónde se puede
      ahorrar, qué categoría creció y si hay cargos que se repiten.</p>
      <button class="boton boton-acento" data-insights>Analizar mis gastos</button>`;
  }

  return `
    <section class="tarjeta" aria-labelledby="titulo-insights">
      <h2 id="titulo-insights" class="tarjeta-titulo">Insights</h2>
      ${cuerpo}
    </section>`;
}

function vistaDesglose(contenedor, ctx, resumen) {
  const { moneda, monedas, periodo, setMoneda, setCategoria } = ctx;

  contenedor.innerHTML = `
    <section class="bloque">
      <h1 class="pantalla-titulo">Gastos</h1>
      ${chipsMoneda({ monedas, moneda })}
      <p class="etiqueta">Gastado en ${esc(periodo.etiqueta)}</p>
      <p class="cifra-heroe" data-contar="${resumen.total}" data-moneda="${esc(moneda)}">${monto(resumen.total, moneda)}</p>
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
    </section>

    ${resumen.categorias.length ? panelInsights(ctx) : ""}`;

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

  for (const boton of contenedor.querySelectorAll("[data-insights]")) {
    boton.addEventListener("click", () => ctx.analizarGastos?.());
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

  // El termómetro va al final y mira TODO el historial, no el período: comparar
  // precios necesita meses. Se agrega después de que vistaDesglose escribió su
  // innerHTML, porque si no lo borraría.
  if (ctx.historialGastos?.length) {
    // Los tres miran TODO el historial, no el período: comparar precios,
    // detectar periodicidad y promediar seis meses necesitan meses.
    renderComparacion(contenedor, {
      historial: ctx.historialGastos.concat(ctx.historialAhorros ?? []),
      delPeriodo: movimientos,
      mesActual: (periodo?.desde ?? "").slice(0, 7),
      moneda,
    });
    renderRecurrentes(contenedor, {
      historial: ctx.historialGastos,
      moneda,
      hoy: ctx.hoy,
    });
    renderTermometro(contenedor, {
      historial: ctx.historialGastos,
      moneda,
      inflacionOficial: ctx.inflacionOficial ?? null,
    });
  }
}
