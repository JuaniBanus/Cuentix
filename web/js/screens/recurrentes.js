// Paneles "Gastos recurrentes" y "Comparado con vos mismo", en Gastos.
//
// Los dos comparten una regla: no dicen qué hacer. El primero muestra qué se
// está pagando todos los meses —dato que nadie tiene a mano— y ahí se detiene;
// no sabe si el gimnasio al que no vas es un olvido o una decisión. El segundo
// compara al usuario SOLO consigo mismo: nunca contra otros usuarios ni contra
// promedios externos, porque comparar el gasto propio con el de un desconocido
// no produce información, produce culpa.

import { esc, monto, montosOcultos } from "../format.js";
import { comparar, frase, MESES_PROMEDIO } from "../comparacion.js";
import { detectar, totalMensual } from "../recurrentes.js";

const TOPE = 8;

function pct(valor) {
  if (montosOcultos()) return "••";
  const signo = valor > 0 ? "+" : "";
  return `${signo}${Math.round(valor * 100)}%`;
}

function fechaCortita(iso) {
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];
  const [a, m, d] = iso.split("-");
  return `${Number(d)} ${nombres[Number(m) - 1]} ${a.slice(2)}`;
}

// -------------------------------------------------------- Recurrentes ----

export function renderRecurrentes(contenedor, { historial, moneda, hoy }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta";

  const encontrados = detectar(historial, moneda, hoy);

  if (!encontrados.length) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">🔁 Gastos recurrentes</h2>
      <p class="vacio">
        Todavía no detecté ninguno. Necesito <strong>3 cargos del mismo ítem</strong>,
        espaciados parejo y por montos parecidos.
      </p>
      <p class="apunte">Mejora bastante con más meses cargados.</p>`;
    contenedor.append(seccion);
    return;
  }

  const total = totalMensual(encontrados);
  const veteranos = encontrados.filter((r) => r.mesesActivo >= 6);

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">🔁 Gastos recurrentes</h2>
    <p class="cifra-media">${monto(total, moneda)}<span class="titulo-nota"> por mes</span></p>
    <p class="apunte">
      ${encontrados.length} ${encontrados.length === 1 ? "cargo que se repite" : "cargos que se repiten"}
      con monto y frecuencia estables.
    </p>

    <ul class="termo-lista">
      ${encontrados.slice(0, TOPE).map((r) => `
        <li class="termo-fila">
          <span class="termo-texto">
            <span class="termo-nombre">${esc(r.clave)}</span>
            <span class="termo-sub">
              ${esc(r.periodo)} · ${r.cargos} cargos · desde ${fechaCortita(r.primero)}
              ${r.vencido ? " · <strong>sin cargo hace un tiempo</strong>" : ""}
            </span>
          </span>
          <span class="termo-cifras">
            <span class="termo-var">${monto(r.montoTipico, moneda)}</span>
            <span class="termo-tem">${monto(r.porMes, moneda)}/mes</span>
          </span>
        </li>`).join("")}
    </ul>
    ${encontrados.length > TOPE ? `<p class="apunte">…y ${encontrados.length - TOPE} más.</p>` : ""}

    ${veteranos.length ? `
      <h3 class="termo-subtitulo">Vienen de hace rato</h3>
      <p class="apunte">Por si querés revisarlos. Si los usás, están bien donde están.</p>
      <ul class="termo-lista">
        ${veteranos.slice(0, 3).map((r) => `
          <li class="termo-fila">
            <span class="termo-texto">
              <span class="termo-nombre">${esc(r.clave)}</span>
              <span class="termo-sub">${r.mesesActivo} meses · ${monto(r.totalPagado, moneda)} acumulados</span>
            </span>
          </li>`).join("")}
      </ul>` : ""}

    <p class="apunte termo-nota">
      Esto mejora con el tiempo: cuantos más meses tengas cargados, mejor
      distingo una suscripción de una coincidencia.
    </p>`;

  contenedor.append(seccion);
}

// --------------------------------------------- Comparación con vos mismo --

export function renderComparacion(contenedor, { historial, delPeriodo, mesActual, moneda }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta";

  const { gasto, tasaAhorro, porCategoria } = comparar(historial, delPeriodo, mesActual, moneda);

  if (!gasto && !tasaAhorro && !porCategoria.length) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">📊 Comparado con vos mismo</h2>
      <p class="vacio">
        Necesito al menos dos meses anteriores cargados para poder decirte si
        este mes se sale de lo tuyo.
      </p>`;
    contenedor.append(seccion);
    return;
  }

  const claseDe = (v) => (v > 0 ? "es-baja" : "es-suba"); // gastar más no es bueno

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">📊 Comparado con vos mismo</h2>

    ${gasto ? `
      <p class="apunte">
        Gastaste <strong class="${claseDe(gasto.variacion)}">${pct(gasto.variacion)}</strong>
        que tu promedio de los últimos ${gasto.meses}
        ${gasto.meses === 1 ? "mes" : "meses"}
        (${monto(gasto.promedio, moneda)}).
      </p>` : ""}

    ${tasaAhorro ? `
      <p class="apunte">
        Ahorraste el ${(tasaAhorro.actual * 100).toFixed(0)}% de lo que entró,
        contra ${(tasaAhorro.promedio * 100).toFixed(0)}% de tu promedio
        <strong class="${tasaAhorro.variacion >= 0 ? "es-suba" : "es-baja"}">
          (${pct(tasaAhorro.variacion)})</strong>.
      </p>` : ""}

    ${porCategoria.length ? `
      <h3 class="termo-subtitulo">Lo que más se salió de lo tuyo</h3>
      <ul class="termo-lista">
        ${porCategoria.slice(0, 6).map((c) => `
          <li class="termo-fila">
            <span class="termo-texto">
              <span class="termo-nombre">${esc(frase(c.categoria, c.variacion))}</span>
              <span class="termo-sub">
                ${monto(c.actual, moneda)} contra ${monto(c.promedio, moneda)} habitual
              </span>
            </span>
            <span class="termo-cifras">
              <span class="termo-var ${claseDe(c.variacion)}">${pct(c.variacion)}</span>
            </span>
          </li>`).join("")}
      </ul>` : ""}

    <p class="apunte termo-nota">
      Siempre contra vos mismo, nunca contra otros: tu promedio de los últimos
      ${MESES_PROMEDIO} meses, sin contar el actual. Un mes sin datos no cuenta
      como cero.
    </p>`;

  contenedor.append(seccion);
}
