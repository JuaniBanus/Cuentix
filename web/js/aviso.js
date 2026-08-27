// El aviso que se muestra cuando algo no se pudo traer.

import { esc } from "./format.js";

export function renderAviso(contenedor, { mensaje, esDeConexion = false, onReintentar }) {
  contenedor.innerHTML = `
    <section class="aviso" role="alert">
      <svg viewBox="0 0 24 24" class="icono aviso-icono" aria-hidden="true">
        <use href="#${esDeConexion ? "i-sin-senal" : "i-aviso"}"></use>
      </svg>
      <p class="aviso-titulo">${esDeConexion ? "Sin conexión" : "Algo no salió bien"}</p>
      <p class="apunte">${esc(mensaje)}</p>
      ${onReintentar ? `<button class="boton boton-acento aviso-boton">Reintentar</button>` : ""}
    </section>`;

  contenedor.querySelector(".aviso-boton")?.addEventListener("click", onReintentar);
}
