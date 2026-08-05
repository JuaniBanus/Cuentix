// Objetivos de ahorro: la lista y el formulario.
//
// El formulario es una vista de la pantalla, no una ventana flotante encima.
// En un celular ocupa todo igual, y así no hay que resolver el foco atrapado,
// el scroll bloqueado ni el fondo que se cierra al tocarlo: los tres bugs
// clásicos de una hoja modal.

import { esc, monto } from "../format.js";
import {
  COLORES, ICONOS, mesYAnio, ordenar, PRIORIDADES, progresoDe, proyeccion,
} from "../objetivos.js";

const ETIQUETA_ESTADO = {
  activo: "",
  pausado: "en pausa",
  completado: "completado ✅",
};

// --------------------------------------------------------------------------
// Lista
// --------------------------------------------------------------------------

function tarjetaObjetivo({ objetivo, progreso, estado }) {
  const color = COLORES.includes(objetivo.color) ? `var(--${objetivo.color})` : "var(--cat-1)";
  const adelanto = proyeccion(progreso);

  const pie = [];
  if (objetivo.fecha_estimada) pie.push(`para ${esc(mesYAnio(objetivo.fecha_estimada))}`);
  if (adelanto) {
    pie.push(
      adelanto.lejisimos
        ? "a este ritmo, faltan más de 10 años"
        : `a este ritmo, ${adelanto.meses} ${adelanto.meses === 1 ? "mes" : "meses"} (${adelanto.etiqueta})`
    );
  }

  return `
    <li>
      <button class="objetivo ${estado === "completado" ? "es-completado" : ""}"
              data-objetivo="${esc(objetivo.id)}">
        <span class="objetivo-icono" style="background:${color}1f; border-color:${color}"
              aria-hidden="true">${esc(objetivo.icono || "🎯")}</span>

        <span class="objetivo-nombre">${esc(objetivo.nombre)}</span>
        <span class="objetivo-etiquetas">
          <span class="tejuelo tejuelo-${esc(objetivo.prioridad)}">${esc(objetivo.prioridad)}</span>
          ${ETIQUETA_ESTADO[estado] ? `<span class="tejuelo">${ETIQUETA_ESTADO[estado]}</span>` : ""}
        </span>

        <span class="objetivo-barra">
          <span class="barra-riel">
            <span class="barra-relleno" style="width:${progreso.porcentaje}%; background:${color}"></span>
          </span>
        </span>

        <span class="objetivo-cifras">
          <span class="barra-monto">${monto(progreso.aportado, objetivo.moneda)}</span>
          <span class="apunte"> de ${monto(progreso.meta, objetivo.moneda)}</span>
        </span>
        <span class="barra-pct">${progreso.porcentajeReal.toFixed(0)}%</span>

        ${pie.length ? `<span class="objetivo-pie apunte">${pie.join(" · ")}</span>` : ""}
      </button>
    </li>`;
}

export function seccionObjetivos(objetivos, ahorros) {
  const ordenados = ordenar(objetivos, ahorros);

  return `
    <section class="tarjeta" aria-labelledby="titulo-objetivos">
      <div class="tarjeta-cabecera">
        <h2 id="titulo-objetivos" class="tarjeta-titulo">Objetivos</h2>
        <button class="boton-icono" data-nuevo-objetivo aria-label="Nuevo objetivo">
          <svg viewBox="0 0 24 24" class="icono"><use href="#i-mas"></use></svg>
        </button>
      </div>

      ${ordenados.length
        ? `<ul class="objetivos">${ordenados.map(tarjetaObjetivo).join("")}</ul>`
        : `<p class="vacio">Todavía no tenés objetivos.<br>
             Creá uno y mirá cómo se va llenando con lo que apartás.</p>`}
    </section>`;
}

export function engancharObjetivos(contenedor, { abrirObjetivo }) {
  contenedor.querySelector("[data-nuevo-objetivo]")?.addEventListener("click", () => abrirObjetivo("nuevo"));
  for (const boton of contenedor.querySelectorAll("[data-objetivo]")) {
    boton.addEventListener("click", () => abrirObjetivo(boton.dataset.objetivo));
  }
}

// --------------------------------------------------------------------------
// Formulario
// --------------------------------------------------------------------------

const opciones = (valores, elegido, atributo) =>
  valores.map((v) => `
    <button type="button" class="chip ${v === elegido ? "es-activo" : ""}" data-${atributo}="${v}">${v}</button>
  `).join("");

export function renderFormObjetivo(contenedor, ctx) {
  const { objetivos, vistaObjetivo, guardando, errorObjetivo, confirmandoBorrado } = ctx;

  const esNuevo = vistaObjetivo === "nuevo";
  const objetivo = esNuevo
    ? { nombre: "", descripcion: "", monto_objetivo: "", moneda: "ARS", fecha_estimada: "",
        prioridad: "media", icono: ICONOS[0], color: COLORES[0], estado: "activo" }
    : objetivos.find((o) => o.id === vistaObjetivo);

  // El objetivo se borró en otra pestaña, o el id quedó viejo.
  if (!objetivo) {
    contenedor.innerHTML = `<p class="vacio">Ese objetivo ya no está.</p>`;
    return;
  }

  contenedor.innerHTML = `
    <section class="bloque">
      <button class="boton-volver" data-volver>
        <svg viewBox="0 0 24 24" class="icono"><use href="#i-izquierda"></use></svg>
        Ahorros
      </button>
      <h1 class="pantalla-titulo">${esNuevo ? "Nuevo objetivo" : "Editar objetivo"}</h1>
    </section>

    <form class="tarjeta form-objetivo" novalidate>
      <label class="campo">
        <span>Nombre</span>
        <input name="nombre" maxlength="60" required value="${esc(objetivo.nombre)}"
               placeholder="Viaje a Japón">
      </label>

      <label class="campo">
        <span>Descripción <span class="apunte">(opcional)</span></span>
        <textarea name="descripcion" maxlength="300" rows="2"
                  placeholder="Dos semanas, en primavera">${esc(objetivo.descripcion ?? "")}</textarea>
      </label>

      <label class="campo">
        <span>Monto objetivo</span>
        <input name="monto_objetivo" type="number" inputmode="decimal" min="0.01" step="0.01"
               required value="${esc(objetivo.monto_objetivo)}" placeholder="500000">
      </label>

      <div class="campo">
        <span>Moneda</span>
        <div class="chips" data-grupo="moneda">${opciones(["ARS", "USD"], objetivo.moneda, "moneda")}</div>
      </div>

      <label class="campo">
        <span>Fecha estimada <span class="apunte">(opcional)</span></span>
        <input name="fecha_estimada" type="date" value="${esc(objetivo.fecha_estimada ?? "")}">
      </label>

      <div class="campo">
        <span>Prioridad</span>
        <div class="chips" data-grupo="prioridad">${opciones(PRIORIDADES, objetivo.prioridad, "prioridad")}</div>
      </div>

      <div class="campo">
        <span>Ícono</span>
        <div class="grilla-iconos" data-grupo="icono">
          ${ICONOS.map((i) => `
            <button type="button" class="icono-opcion ${i === objetivo.icono ? "es-activo" : ""}"
                    data-icono="${i}" aria-label="Ícono ${i}">${i}</button>
          `).join("")}
        </div>
      </div>

      <div class="campo">
        <span>Color</span>
        <div class="grilla-colores" data-grupo="color">
          ${COLORES.map((c) => `
            <button type="button" class="color-opcion ${c === objetivo.color ? "es-activo" : ""}"
                    data-color="${c}" style="background:var(--${c})" aria-label="Color ${c}"></button>
          `).join("")}
        </div>
      </div>

      ${esNuevo ? "" : `
        <div class="campo">
          <span>Estado</span>
          <div class="chips" data-grupo="estado">${opciones(["activo", "pausado"], objetivo.estado, "estado")}</div>
        </div>`}

      <p class="error">${esc(errorObjetivo ?? "")}</p>

      <button type="submit" class="boton boton-acento" ${guardando ? "disabled" : ""}>
        ${guardando ? "Guardando…" : esNuevo ? "Crear objetivo" : "Guardar cambios"}
      </button>
    </form>

    ${esNuevo ? "" : `
      <section class="bloque">
        ${confirmandoBorrado
          ? `<div class="confirmar">
               <p class="apunte">¿Borrar «${esc(objetivo.nombre)}»? Los ahorros que le imputaste
                  no se borran, solo dejan de estar asignados.</p>
               <div class="confirmar-botones">
                 <button class="boton" data-cancelar-borrado>No</button>
                 <button class="boton boton-peligro" data-borrar>Sí, borrar</button>
               </div>
             </div>`
          : `<button class="boton boton-con-icono" data-pedir-borrado>
               <svg viewBox="0 0 24 24" class="icono"><use href="#i-basura"></use></svg>
               Borrar objetivo
             </button>`}
      </section>`}`;

  // ---- eventos ----
  const form = contenedor.querySelector("form");

  // Los chips y las grillas son botones, no inputs: el valor elegido se lee de
  // la clase al enviar, y tocarlos solo mueve el resaltado.
  for (const grupo of contenedor.querySelectorAll("[data-grupo]")) {
    for (const boton of grupo.querySelectorAll("button")) {
      boton.addEventListener("click", () => {
        for (const otro of grupo.querySelectorAll("button")) {
          otro.classList.toggle("es-activo", otro === boton);
        }
      });
    }
  }

  const elegido = (grupo, atributo) =>
    contenedor.querySelector(`[data-grupo="${grupo}"] .es-activo`)?.dataset[atributo] ?? null;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    ctx.guardarObjetivo({
      nombre: form.nombre.value.trim(),
      descripcion: form.descripcion.value.trim() || null,
      monto_objetivo: form.monto_objetivo.value,
      moneda: elegido("moneda", "moneda"),
      // Un date vacío es "": la columna espera null o una fecha, nunca "".
      fecha_estimada: form.fecha_estimada.value || null,
      prioridad: elegido("prioridad", "prioridad"),
      icono: elegido("icono", "icono"),
      color: elegido("color", "color"),
      ...(esNuevo ? {} : { estado: elegido("estado", "estado") }),
    });
  });

  contenedor.querySelector("[data-volver]").addEventListener("click", () => ctx.abrirObjetivo(null));
  contenedor.querySelector("[data-pedir-borrado]")?.addEventListener("click", () => ctx.pedirBorrado(true));
  contenedor.querySelector("[data-cancelar-borrado]")?.addEventListener("click", () => ctx.pedirBorrado(false));
  contenedor.querySelector("[data-borrar]")?.addEventListener("click", () => ctx.borrarObjetivo(objetivo.id));
}
