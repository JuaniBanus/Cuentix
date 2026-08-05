// El aviso que se muestra cuando algo no se pudo traer.
//
// Es una tarjeta y no un alert() ni un texto suelto: la app sigue entera abajo,
// se explica qué pasó y hay un botón para volver a intentar sin recargar.

import { esc } from "./format.js";

/**
 * @param {HTMLElement} contenedor
 * @param {{mensaje: string, esDeConexion?: boolean, onReintentar?: () => void}} aviso
 */
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
