// Retos de ahorro: el activo y los logros, dentro de Ahorros.

import { esc, monto } from "../format.js";

const MESES = ["ene", "feb", "mar", "abr", "may", "jun",
               "jul", "ago", "sep", "oct", "nov", "dic"];

function fechaCorta(iso) {
  const [, m, d] = iso.split("-");
  return `${Number(d)} ${MESES[Number(m) - 1]}`;
}

function barraDeDias(reto, hoy) {
  const desde = new Date(reto.desde);
  const hasta = new Date(reto.hasta);
  const total = Math.max((hasta - desde) / 86400000, 1);
  const pasados = Math.min(Math.max((new Date(hoy) - desde) / 86400000, 0), total);
  return Math.round((pasados / total) * 100);
}

export function renderRetos(contenedor, { retos, moneda, hoy }) {
  const todos = retos ?? [];
  if (!todos.length) return;

  const activo = todos.find((r) => r.estado === "activo");
  const cumplidos = todos.filter((r) => r.estado === "cumplido");
  const cerrados = todos.filter((r) => r.estado !== "activo").slice(0, 6);

  const seccion = document.createElement("section");
  seccion.className = "tarjeta";

  const ahorrado = cumplidos.reduce((t, r) => t + (Number(r.ahorro_estimado) || 0), 0);

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">🎯 Retos de ahorro</h2>

    ${activo ? `
      <div class="reto-activo">
        <p class="reto-nombre">Una semana sin ${esc(activo.categoria)}</p>
        <span class="barra-pista">
          <span class="barra-relleno" style="width:${barraDeDias(activo, hoy)}%;
                background:var(--acento)"></span>
        </span>
        <p class="apunte">
          Del ${fechaCorta(activo.desde)} al ${fechaCorta(activo.hasta)} ·
          ahorro estimado ${monto(Number(activo.ahorro_estimado), moneda)}
        </p>
      </div>` : `
      <p class="apunte">
        No tenés ningún reto activo. Pedile uno al bot con <strong>/reto</strong>:
        te propone algo según lo que venís gastando.
      </p>`}

    ${cumplidos.length ? `
      <p class="apunte reto-logros">
        🏆 ${cumplidos.length} ${cumplidos.length === 1 ? "reto cumplido" : "retos cumplidos"} ·
        ${monto(ahorrado, moneda)} ahorrados según lo estimado.
      </p>` : ""}

    ${cerrados.length ? `
      <ul class="termo-lista">
        ${cerrados.map((r) => `
          <li class="termo-fila">
            <span class="termo-texto">
              <span class="termo-nombre">
                ${r.estado === "cumplido" ? "🏆" : "—"} ${esc(r.categoria)}
              </span>
              <span class="termo-sub">
                ${fechaCorta(r.desde)} al ${fechaCorta(r.hasta)} ·
                ${r.estado === "cumplido" ? "cumplido" : "no salió"}
              </span>
            </span>
            <span class="termo-cifras">
              <span class="termo-var ${r.estado === "cumplido" ? "es-suba" : ""}">
                ${r.estado === "cumplido" ? monto(Number(r.ahorro_estimado), moneda) : ""}
              </span>
            </span>
          </li>`).join("")}
      </ul>` : ""}

    <p class="apunte termo-nota">
      El ahorro de cada reto es una estimación sacada de lo que venías gastando
      en ese rubro, no una medición exacta.
    </p>`;

  contenedor.append(seccion);
}
