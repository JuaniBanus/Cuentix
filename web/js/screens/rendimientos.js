// Panel "Dónde rinde más tu plata", dentro de Ahorros.

import { esc, monto } from "../format.js";

const MONTO_INICIAL = 100000;

const DIAS_PARA_AVISAR = 7;

const ETIQUETA_TIPO = {
  fci: "Fondo común",
  cuenta_remunerada: "Cuenta remunerada",
};

/** Los días que pasaron desde una fecha ISO. null si no se puede leer. */
function diasDesde(iso, hoy) {
  const cuando = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(cuando.getTime())) return null;
  const referencia = new Date(`${hoy}T00:00:00`);
  if (Number.isNaN(referencia.getTime())) return null;
  return Math.floor((referencia - cuando) / 86400000);
}

function fechaLarga(iso) {
  const cuando = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(cuando.getTime())) return iso;
  return cuando.toLocaleDateString("es-AR", { day: "numeric", month: "long", year: "numeric" });
}

function pct(valor) {
  return `${valor.toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

/** Lo que rinde un capital a esa TNA. */
function ganancia(capital, tna) {
  const mensual = tna / 100 / 12;
  return {
    mes: capital * mensual,
    anio: capital * ((1 + mensual) ** 12 - 1),
  };
}

function filaTabla(fila, capital) {
  const tna = Number(fila.tna);
  if (!Number.isFinite(tna)) return "";

  const tope = fila.tope_monto == null ? null : Number(fila.tope_monto);
  const tieneTope = tope !== null && Number.isFinite(tope) && tope > 0;
  const base = tieneTope ? Math.min(capital, tope) : capital;
  const excedido = tieneTope && capital > tope;

  const { mes, anio } = ganancia(base, tna);

  return `
    <li class="rend-fila">
      <div class="rend-quien">
        <span class="rend-nombre">${esc(fila.nombre)}</span>
        <span class="rend-tipo">${esc(ETIQUETA_TIPO[fila.tipo] ?? fila.tipo)}</span>
        ${excedido
          ? `<span class="rend-aviso-tope">paga solo hasta ${monto(tope, "ARS")}</span>`
          : tieneTope
            ? `<span class="rend-tope">tope ${monto(tope, "ARS")}</span>`
            : ""}
      </div>
      <span class="rend-tna">${pct(tna)}<span class="rend-tna-nota">TNA</span></span>
      <span class="rend-gana">
        <span class="rend-gana-mes">${monto(mes, "ARS")}</span>
        <span class="rend-gana-anio">${monto(anio, "ARS")} al año</span>
      </span>
    </li>`;
}

/** Reescribe solo las filas. Se llama en cada tecla del simulador. */
function pintarFilas(lista, filas, capital) {
  lista.innerHTML = filas.map((f) => filaTabla(f, capital)).join("");
}

export function renderRendimientos(contenedor, { rendimientos, hoy }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta rend";

  if (!rendimientos?.length) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">💰 Dónde rinde más tu plata</h2>
      <p class="vacio">
        Todavía no tengo las tasas de las billeteras.<br>
        Las actualiza un proceso automático una vez por día; el resto de la
        pantalla funciona igual.
      </p>`;
    contenedor.append(seccion);
    return;
  }

  const filas = [...rendimientos]
    .filter((f) => Number.isFinite(Number(f.tna)))
    .sort((a, b) => Number(b.tna) - Number(a.tna));

  const fechas = filas.map((f) => f.fecha_actualizacion).filter(Boolean).sort();
  const masVieja = fechas[0] ?? null;
  const atraso = masVieja ? diasDesde(masVieja, hoy) : null;
  const vieja = atraso !== null && atraso > DIAS_PARA_AVISAR;

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">💰 Dónde rinde más tu plata</h2>

    <p class="rend-fecha ${vieja ? "es-vieja" : ""}">
      ${masVieja
        ? `${vieja ? "⚠️" : "📅"} Tasas al <strong>${esc(fechaLarga(masVieja))}</strong>${
            atraso === 0 ? " · de hoy" : atraso === 1 ? " · de ayer" : ` · hace ${atraso} días`
          }`
        : "📅 Sin fecha de actualización"}
    </p>
    ${vieja
      ? `<p class="apunte rend-alerta">
           Hace más de ${DIAS_PARA_AVISAR} días que no se actualizan: puede que la
           fuente esté caída. Verificá en la app de tu billetera antes de mover plata.
         </p>`
      : ""}

    <div class="rend-simulador">
      <label class="rend-label" for="rend-monto">Si pongo</label>
      <div class="rend-input-grupo">
        <span class="rend-signo">$</span>
        <input id="rend-monto" class="rend-input" type="number" inputmode="numeric"
               min="0" step="10000" value="${MONTO_INICIAL}"
               aria-label="Monto a simular, en pesos">
      </div>
      <span class="rend-label rend-label-fin">gano por mes</span>
    </div>

    <ul class="rend-tabla" id="rend-tabla"></ul>

    <p class="apunte rend-nota">
      Rendimientos variables y no garantizados: la mayoría sale de un fondo común
      de dinero y la tasa cambia todos los días. La ganancia anual supone dejar la
      plata quieta y reinvertir. Datos públicos de la CAFCI vía argentinadatos.
    </p>`;

  contenedor.append(seccion);

  const lista = seccion.querySelector("#rend-tabla");
  const input = seccion.querySelector("#rend-monto");

  const refrescar = () => {
    const capital = Math.max(0, Number(input.value) || 0);
    pintarFilas(lista, filas, capital);
  };

  refrescar();
  input.addEventListener("input", refrescar);
}
