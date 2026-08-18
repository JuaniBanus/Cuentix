// La barra de secciones: la franja de abajo en el teléfono, la franja de arriba
// en una pantalla grande.
//
// Vive aparte del router porque no es ruteo, es presentación: acá no se decide
// a dónde se va, solo cómo se ve el camino. Además el banco de pruebas
// (_preview.html) la necesita entera para poder mirarla, y sin este archivo
// tendría que copiar la lógica y quedaría desincronizada al primer cambio.
//
// Casi todo el aspecto está en el CSS. Lo que queda acá son las dos cosas que el
// CSS no puede hacer solo: medir dónde está la sección activa, y mudar de lugar
// un nodo cuando cambia el ancho de la ventana.

// A partir de acá la barra deja de ser una franja abajo y pasa a ser la franja
// de arriba. Es el mismo número que el primer salto del CSS, y tiene que serlo:
// si se separan, los controles se mudarían a una barra que todavía no está
// arriba, o al revés.
const PANTALLA_GRANDE = "(min-width: 768px)";

/**
 * Dibuja la barra y la deja funcionando.
 *
 * @param {HTMLElement} nav
 * @param {Array<{id: string, nombre: string, icono: string}>} secciones
 * @param {(id: string) => void} alTocar
 */
export function montarBarra(nav, secciones, alTocar) {
  // Los controles del encabezado VIVEN ADENTRO de esta barra en pantalla
  // grande (ver `mudarControles`), así que el innerHTML de más abajo se los
  // llevaría puestos. Se los devuelve al encabezado antes de arrasar, y
  // `mudarControles` los reubica al final.
  //
  // Hace falta porque la barra se redibuja: al entrar se arma con las secciones
  // del rol, y eso pasa en cada login. La primera versión de esto asumía un
  // solo armado en toda la vida de la página; con dos, el nodo desaparecía del
  // documento y todo lo que lo buscaba después reventaba con null —incluido el
  // botón de cerrar sesión, que dejaba de sacar a nadie—.
  rescatarControles(nav);

  // Las secciones van en dos grupos, y la división la trae cada sección en
  // `aparte`. Las normales se centran en la barra; las apartadas se van al
  // extremo derecho, junto a los controles.
  //
  // Usuario es la única apartada, y no es un capricho de acomodo: no es un lugar
  // donde se mira plata como los otros cuatro, es la cuenta. Ponerla en la fila
  // del medio la haría parecer una quinta vista de datos.
  // Las apartadas se quedan con el ícono solo en pantalla grande, así que llevan
  // title: es lo que aclara el dibujo al pasar el mouse. El <span> con el nombre
  // se queda igual en las dos —escondido a la vista pero presente— porque es de
  // donde el lector de pantalla saca a dónde lleva el botón.
  const boton = (s) => `
    <button class="tab ${s.aparte ? "tab-solo-icono" : ""}" data-tab="${s.id}"
            aria-current="false"${s.aparte ? ` title="${s.nombre}"` : ""}>
      <svg viewBox="0 0 24 24" class="icono"><use href="#${s.icono}"></use></svg>
      <span>${s.nombre}</span>
    </button>`;

  // Los dos grupos existen SIEMPRE, en los dos tamaños. En el teléfono se
  // desarman con `display: contents` y los botones vuelven a ser hijos directos
  // de la barra, así que la franja de abajo se sigue repartiendo entre las cinco
  // secciones como toda la vida. Sin eso, el grid de abajo vería dos cajas en
  // vez de cinco botones y quedarían dos columnas gigantes.
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

  // Al cambiar el ancho la barra pasa de horizontal a vertical y las medidas que
  // tenía la pastilla dejan de valer. Se vuelve a medir la que esté activa, sin
  // repintar la pantalla: esto es geometría, no datos.
  //
  // Se engancha UNA sola vez aunque la barra se rearme muchas: si no, cada
  // login sumaría otro oyente sobre el mismo evento y a la décima vez un
  // simple achicar la ventana dispararía diez mediciones.
  if (!oyenteDeAncho) {
    oyenteDeAncho = () => moverPastilla(nav, nav.querySelector(".tab.es-activo"));
    window.addEventListener("resize", oyenteDeAncho);
  }
}

let oyenteDeAncho = null;

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

// --------------------------------------------------------------------------
// La pastilla del resaltado
// --------------------------------------------------------------------------

/**
 * Lleva la pastilla hasta el botón activo.
 *
 * Se miden los cuatro lados y se los pasa al CSS como variables, en vez de
 * escribir acá qué aspecto tiene que tener. Eso es lo que permite que la misma
 * pieza sea un subrayado fino que corre a lo ancho en el teléfono y un recuadro
 * que sube y baja en la columna: el JS dice DÓNDE está lo activo y cada tamaño
 * de pantalla decide cómo dibuja eso.
 */
function moverPastilla(nav, activo) {
  const pastilla = nav.querySelector(".tabs-pastilla");
  if (!pastilla || !activo) return;

  // Sin layout todavía —la barra escondida, la pestaña en segundo plano— las
  // medidas dan cero y la pastilla se iría a la esquina de arriba. Mejor dejarla
  // donde está: el próximo pintado la acomoda.
  if (!activo.offsetWidth && !activo.offsetHeight) return;

  pastilla.style.setProperty("--x", `${activo.offsetLeft}px`);
  pastilla.style.setProperty("--y", `${activo.offsetTop}px`);
  pastilla.style.setProperty("--w", `${activo.offsetWidth}px`);
  pastilla.style.setProperty("--h", `${activo.offsetHeight}px`);
  pastilla.dataset.lista = "si";
}

// --------------------------------------------------------------------------
// Los controles del encabezado, que en pantalla grande se mudan a la barra
// --------------------------------------------------------------------------
//
// El período, el dólar y el ojo valen para toda la app, así que su lugar es el
// marco y no una pantalla. En el teléfono ese marco es el encabezado; en una
// pantalla grande es la barra de secciones, que a lo ancho tiene lugar de sobra
// a la derecha. Y entonces el encabezado sobra: dos franjas horizontales
// apiladas comen el alto que en un laptop es justo lo que falta.
//
// Se MUDA el nodo en vez de dibujar dos copias y esconder una. Con dos copias
// habría dos #btn-ojo, dos #btn-periodo y dos paneles, y cada módulo que los
// busca por id se quedaría con el primero del documento, que no siempre es el
// que está a la vista. Mudándolo hay uno solo y siempre es el visible.

let oyenteDeUmbral = false;

function mudarControles(nav) {
  const grande = window.matchMedia(PANTALLA_GRANDE);

  const ubicar = () => {
    // Los tres nodos se buscan ACÁ ADENTRO y no se capturan al enganchar. La
    // barra se rearma en cada login, así que un `.tabs-fin` guardado en la
    // clausura apuntaría a un nodo que ya salió del documento, y los controles
    // se mudarían a la nada.
    const controles = document.querySelector(".cabecera-acciones");
    const cabecera = document.querySelector(".cabecera");
    const fin = nav.querySelector(".tabs-fin");
    if (!controles || !cabecera || !fin) return;

    // append y prepend MUEVEN el nodo, no lo copian: se desprende solo de donde
    // estaba y se lleva puestos los eventos ya enganchados. Por eso no hay que
    // volver a conectar nada cada vez que se cruza el umbral.
    //
    // prepend y no append: los controles tienen que quedar ANTES del botón de
    // Usuario, para que el orden de izquierda a derecha sea período, dólar, ojo
    // y recién ahí la personita.
    if (grande.matches) fin.prepend(controles);
    else cabecera.append(controles);
  };

  // Una sola vez, por lo mismo que el de resize.
  if (!oyenteDeUmbral) {
    grande.addEventListener("change", ubicar);
    oyenteDeUmbral = true;
  }
  ubicar();
}
