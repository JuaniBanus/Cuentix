// Panel de administración: quién tiene cuenta y quién puede entrar.
//
// Es la ÚNICA pantalla de datos del superusuario. No muestra un peso de nadie
// —ni podría: las policies restrictivas de migrations/014 le devuelven cero
// filas de movimientos, objetivos e inversiones aunque pida directo a la API—.
// Acá solo hay emails, estados y roles.
//
// LAS ALTAS NO SE HACEN DESDE ACÁ, y es a propósito. Crear un usuario necesita
// la service_role, que no puede vivir en el navegador; hacerlo desde la web
// pedía un endpoint nuevo en el bot, o sea más superficie para proteger. Se
// hacen invitando desde Supabase, y este panel explica cómo. Lo que sí se hace
// acá es lo de todos los días: activar y pausar.

import { esc } from "../format.js";

const ETIQUETA_ESTADO = {
  activo: "Activo",
  pausado: "Pausado",
  pendiente: "Pendiente",
};

const EXPLICACION_ESTADO = {
  activo: "entra y ve lo suyo",
  pausado: "no puede entrar; sus datos quedan intactos",
  pendiente: "creada pero todavía sin habilitar",
};

export function renderAdmin(contenedor, {
  usuarios,
  perfil,
  errorAdmin,
  guardandoUsuario,
  cambiarEstadoUsuario,
  recargarUsuarios,
}) {
  const lista = usuarios ?? [];

  contenedor.innerHTML = `
    <section class="bloque">
      <h1 class="pantalla-titulo">Usuarios</h1>
      <p class="apunte">
        ${lista.length} ${lista.length === 1 ? "cuenta" : "cuentas"} ·
        ${lista.filter((u) => u.estado === "activo").length} con acceso
      </p>
    </section>

    ${errorAdmin ? `
      <section class="tarjeta">
        <p class="error" role="alert">${esc(errorAdmin)}</p>
        <button id="btn-reintentar" class="boton">Reintentar</button>
      </section>` : ""}

    <section class="tarjeta">
      <ul class="lista-usuarios">
        ${lista.map((u) => fila(u, perfil, guardandoUsuario)).join("")}
      </ul>
    </section>

    <section class="tarjeta" aria-labelledby="titulo-alta">
      <h2 id="titulo-alta" class="tarjeta-titulo">Dar de alta a alguien</h2>
      <ol class="pasos-alta">
        <li>
          En Supabase, <b>Authentication → Invite user</b>. Le llega un mail y
          elige su propia contraseña: no pasa por vos en ningún momento.
        </li>
        <li>
          Apenas se registra aparece en esta lista, en <b>Pendiente</b>.
        </li>
        <li>
          La activás con el botón de acá arriba. Recién ahí puede ver algo.
        </li>
      </ol>
      <p class="apunte">
        Si además va a cargar gastos por Telegram, hay que vincular su chat.
        Está explicado en <code>migrations/009_multiusuario.sql</code>.
      </p>
    </section>`;

  const reintentar = contenedor.querySelector("#btn-reintentar");
  if (reintentar) reintentar.addEventListener("click", recargarUsuarios);

  for (const boton of contenedor.querySelectorAll("[data-cambiar]")) {
    boton.addEventListener("click", () => {
      cambiarEstadoUsuario(boton.dataset.cambiar, boton.dataset.estado);
    });
  }
}

function fila(usuario, perfil, guardandoUsuario) {
  const esUnoMismo = usuario.user_id === perfil?.user_id;
  const estado = usuario.estado ?? "pendiente";
  const activo = estado === "activo";
  const guardando = guardandoUsuario === usuario.user_id;

  // Pausar la cuenta propia dejaría el sistema sin ningún superusuario activo y
  // sin forma de volver desde la web. La función admin_cambiar_estado lo
  // rechaza igual; acá se saca el botón para no ofrecer algo que va a fallar.
  const boton = esUnoMismo
    ? `<span class="apunte">sos vos</span>`
    : `<button class="boton boton-chico" type="button"
               data-cambiar="${esc(usuario.user_id)}"
               data-estado="${activo ? "pausado" : "activo"}"
               ${guardando ? "disabled" : ""}>
         ${guardando ? "Guardando…" : activo ? "Pausar" : "Activar"}
       </button>`;

  return `
    <li class="usuario-fila">
      <span class="usuario-datos">
        <span class="usuario-email">${esc(usuario.email ?? "sin email")}</span>
        <span class="apunte">
          ${esc(EXPLICACION_ESTADO[estado] ?? estado)}${
            usuario.rol === "superusuario" ? " · administra usuarios" : ""
          }${usuario.debe_cambiar_password ? " · tiene que cambiar la contraseña" : ""}
        </span>
      </span>
      <span class="estado-chip es-${esc(estado)}">${esc(ETIQUETA_ESTADO[estado] ?? estado)}</span>
      ${boton}
    </li>`;
}
