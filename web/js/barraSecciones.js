// La barra de secciones: la franja de abajo en el teléfono, la franja de arriba

const PANTALLA_GRANDE = "(min-width: 768px)";

/** Dibuja la barra y la deja funcionando. */
export function montarBarra(nav, secciones, alTocar) {
  rescatarControles(nav);

  const boton = (s) => `
    <button class="tab ${s.aparte ? "tab-solo-icono" : ""}" data-tab="${s.id}"
            aria-current="false"${s.aparte ? ` title="${s.nombre}"` : ""}>
      <svg viewBox="0 0 24 24" class="icono"><use href="#${s.icono}"></use></svg>
      <span>${s.nombre}</span>
    </button>`;

  nav.innerHTML = `
    <span class="tabs-pastilla" aria-hidden="true"></span>
    <p class="tabs-marca" aria-hidden="true"
       ><span>C</span><span class="tabs-marca-resto">uentix</span></p>
    <div class="tabs-grupo">${secciones.filter((s) => !s.aparte).map(boton).join("")}</div>
    <div class="tabs-fin">${secciones.filter((s) => s.aparte).map(boton).join("")}</div>`;

  for (const b of nav.querySelectorAll(".tab")) {
    b.addEventListener("click", () => alTocar(b.dataset.tab));
  }

  mudarControles(nav);

  if (oyenteDeAncho) window.removeEventListener("resize", oyenteDeAncho);
  oyenteDeAncho = () => moverPastilla(nav, nav.querySelector(".tab.es-activo"));
  window.addEventListener("resize", oyenteDeAncho);

  // La pastilla se mide con offsetLeft, asi que hay que volver a medirla cada
  // vez que cambian los anchos: cuando entra la tipografia (Inter llega de
  // Google Fonts DESPUES del primer pintado y ensancha cada boton) y cuando se
  // mueven los controles adentro de la barra. Sin esto queda corrida.
  document.fonts?.ready.then(oyenteDeAncho).catch(() => {});
  observarAncho(nav);
}

let oyenteDeAncho = null;
let observador = null;

/** Reubica la pastilla ante cualquier cambio de tamaño de la barra. */
function observarAncho(nav) {
  if (observador) observador.disconnect();
  if (typeof ResizeObserver !== "function") return;
  observador = new ResizeObserver(() => oyenteDeAncho?.());
  observador.observe(nav);
  const grupo = nav.querySelector(".tabs-grupo");
  if (grupo) observador.observe(grupo);
}

/** Devuelve los controles al encabezado si estaban dentro de la barra. */
function rescatarControles(nav) {
  const controles = nav.querySelector(".cabecera-acciones");
  const cabecera = document.querySelector(".cabecera");
  if (controles && cabecera) cabecera.append(controles);
}

/** Marca qué sección se está viendo y lleva la pastilla hasta ella. */
export function marcarActiva(nav, id) {
  let activo = null;

  for (const boton of nav.querySelectorAll(".tab")) {
    const esta = boton.dataset.tab === id;
    boton.classList.toggle("es-activo", esta);
    boton.setAttribute("aria-current", esta ? "page" : "false");
    if (esta) activo = boton;
  }

  moverPastilla(nav, activo);
}


/** Lleva la pastilla hasta el botón activo. */
function moverPastilla(nav, activo) {
  const pastilla = nav.querySelector(".tabs-pastilla");
  if (!pastilla || !activo) return;

  if (!activo.offsetWidth && !activo.offsetHeight) return;

  const grupo = activo.offsetParent === nav ? null : activo.offsetParent;
  const dx = grupo ? grupo.offsetLeft : 0;
  const dy = grupo ? grupo.offsetTop : 0;

  pastilla.style.setProperty("--x", `${activo.offsetLeft + dx}px`);
  pastilla.style.setProperty("--y", `${activo.offsetTop + dy}px`);
  pastilla.style.setProperty("--w", `${activo.offsetWidth}px`);
  pastilla.style.setProperty("--h", `${activo.offsetHeight}px`);
  pastilla.dataset.lista = "si";
}


let oyenteDeUmbral = false;

function mudarControles(nav) {
  const grande = window.matchMedia(PANTALLA_GRANDE);

  const ubicar = () => {
    const controles = document.querySelector(".cabecera-acciones");
    const cabecera = document.querySelector(".cabecera");
    const fin = nav.querySelector(".tabs-fin");
    if (!controles || !cabecera || !fin) return;

    if (grande.matches) fin.prepend(controles);
    else cabecera.append(controles);
  };

  if (!oyenteDeUmbral) {
    grande.addEventListener("change", ubicar);
    oyenteDeUmbral = true;
  }
  ubicar();
}
