// Pantalla Usuario: quién está adentro, ajustes y salida.

import { esc } from "../format.js";
import { alternarTema, temaActual } from "../tema.js";

export function renderUsuario(contenedor, { email, onSalir }) {
  const inicial = (email || "?").charAt(0).toUpperCase();
  const claro = temaActual() === "claro";

  contenedor.innerHTML = `
    <section class="bloque">
      <h1 class="pantalla-titulo">Usuario</h1>
    </section>

    <section class="tarjeta">
      <div class="perfil">
        <span class="perfil-avatar" aria-hidden="true">${esc(inicial)}</span>
        <span class="perfil-datos">
          <span class="perfil-email">${esc(email || "Sin email")}</span>
          <span class="apunte">Sesión iniciada</span>
        </span>
      </div>
    </section>

    <section class="tarjeta" aria-labelledby="titulo-ajustes">
      <h2 id="titulo-ajustes" class="tarjeta-titulo">Ajustes</h2>
      <div class="ajuste">
        <span class="ajuste-texto">
          <span>Tema claro</span>
          <span class="apunte" id="tema-apunte">${claro ? "Activado" : "Estás en modo oscuro"}</span>
        </span>
        <button id="btn-tema" class="interruptor" type="button"
                role="switch" aria-checked="${claro}" aria-label="Tema claro"></button>
      </div>
    </section>

    <section class="bloque">
      <button id="btn-salir" class="boton boton-con-icono">
        <svg viewBox="0 0 24 24" class="icono"><use href="#i-salir"></use></svg>
        Cerrar sesión
      </button>
    </section>`;

  const btnTema = contenedor.querySelector("#btn-tema");
  btnTema.addEventListener("click", () => {
    const esClaro = alternarTema() === "claro";
    btnTema.setAttribute("aria-checked", String(esClaro));
    contenedor.querySelector("#tema-apunte").textContent =
      esClaro ? "Activado" : "Estás en modo oscuro";
  });

  contenedor.querySelector("#btn-salir").addEventListener("click", onSalir);
}
