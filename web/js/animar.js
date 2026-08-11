// El movimiento que el CSS no puede hacer solo.
//
// Casi todo lo que se mueve en la app vive en styles.css. Acá quedan las tres
// cosas que necesitan saber algo que solo se conoce en tiempo de ejecución:
//
//   - el largo de un trazo SVG, para dibujarlo de punta a punta;
//   - el valor final de una cifra, para contarla desde cero;
//   - si este repintado viene de haber cambiado de sección o de haber tocado el
//     ojo, porque lo primero merece una entrada y lo segundo no.
//
// Nada de esto es decorativo por sí solo. Una cifra que sube y una línea que se
// dibuja dicen "esto se acaba de calcular", que es información: sin movimiento,
// un número que cambia de 180.000 a 181.500 al cambiar de mes puede pasar
// entero desapercibido.

import { monto } from "./format.js";

/**
 * Si la persona pidió menos movimiento, no hay animación y punto.
 *
 * Se consulta en cada llamada y no se guarda en una constante: la preferencia
 * se puede cambiar con la app abierta, y quien la cambia espera que valga ya.
 */
export function sinMovimiento() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// --------------------------------------------------------------------------
// Si este pintado merece animarse
// --------------------------------------------------------------------------
//
// `pintar()` corre por muchos motivos: se cambió de sección, se tocó el ojo, se
// cambió de moneda, llegó una cotización. Solo el primero merece que la pantalla
// entre y que los gráficos se dibujen; en los demás la persona está mirando el
// dato y volver a animarlo se lo esconde medio segundo.
//
// El aviso llega del router, que es el único que sabe por qué está pintando. Se
// lee durante el render —todo el pintado es sincrónico— y se baja al terminar.

let animandoEstePintado = false;

/** @param {boolean} conEntrada true solo si se cambió de sección. */
export function empezarPintado(conEntrada) {
  animandoEstePintado = conEntrada && !sinMovimiento();
}

export function terminarPintado() {
  animandoEstePintado = false;
}

/** Lo llaman los gráficos para saber si les toca dibujarse o aparecer y ya. */
export function hayQueAnimar() {
  return animandoEstePintado;
}

// --------------------------------------------------------------------------
// Cifras que suben
// --------------------------------------------------------------------------

// Arriba de este umbral el conteo se corta: nadie sigue con la vista una cifra
// que tarda más que esto, y en una pantalla con cuatro se vuelve un ruido.
const DURACION = 650;

/**
 * Frena rápido al final. Es la misma sensación que --curva en el CSS: los
 * últimos dígitos se acomodan enseguida en vez de arrastrarse.
 */
const suavizar = (t) => 1 - Math.pow(1 - t, 3);

/**
 * Cuenta una cifra desde cero hasta su valor.
 *
 * Recibe el formateador en vez de formatear acá: el texto final tiene que pasar
 * por el mismo `monto()` que el resto de la app, que es el que sabe del ojo, de
 * la conversión a dólares y del formato argentino. Duplicar esa lógica sería
 * garantizar que en algún momento el número animado y el quieto no coincidan.
 *
 * @param {HTMLElement} nodo
 * @param {number} valor
 * @param {(v: number) => string} formatear
 */
export function contarHasta(nodo, valor, formatear) {
  const final = formatear(valor);

  // Sin movimiento, con el ojo tapado o con un valor que no es un número: se
  // escribe y listo. El chequeo de `final` cubre el ojo sin tener que
  // preguntarle por él: si lo que sale son puntitos, no hay nada que contar.
  if (sinMovimiento() || !Number.isFinite(valor) || !/\d/.test(final)) {
    nodo.textContent = final;
    return;
  }

  const arranque = performance.now();

  // Se escribe el valor final ANTES del primer cuadro. Si algo falla —una
  // pestaña en segundo plano que nunca corre el rAF, un navegador que lo
  // limita— el número correcto ya está en pantalla, y lo peor que pasa es que
  // no se animó.
  nodo.textContent = final;

  function cuadro(ahora) {
    const avance = Math.min((ahora - arranque) / DURACION, 1);
    nodo.textContent = avance === 1 ? final : formatear(valor * suavizar(avance));
    if (avance < 1) requestAnimationFrame(cuadro);
  }

  requestAnimationFrame(cuadro);
}

/**
 * Cuenta todas las cifras marcadas de una pantalla.
 *
 * Las pantallas no llaman a nadie: marcan la cifra con `data-contar` y siguen
 * siendo funciones que devuelven HTML. Así no hay cinco pantallas repitiendo la
 * misma llamada, y una pantalla nueva hereda el comportamiento con solo poner el
 * atributo.
 */
export function animarCifras(contenedor) {
  for (const nodo of contenedor.querySelectorAll("[data-contar]")) {
    const valor = Number(nodo.dataset.contar);
    const moneda = nodo.dataset.moneda || "ARS";
    // Ganancia y pérdida se escriben con signo adelante; los totales, no.
    const signo = nodo.dataset.signo === "si";
    contarHasta(nodo, valor, (v) => monto(v, moneda, { signo }));
  }
}

// --------------------------------------------------------------------------
// Trazos que se dibujan
// --------------------------------------------------------------------------

/**
 * Dibuja un path de punta a punta.
 *
 * El truco es viejo y sigue siendo el mejor: se le pone al trazo un guión tan
 * largo como él mismo y se lo empuja fuera de la vista con el offset; al llevar
 * el offset a cero, el guión entra y parece que se está dibujando.
 *
 * @param {SVGPathElement} trazo
 * @param {number} duracion
 */
export function dibujarTrazo(trazo, duracion = 900) {
  if (!trazo || sinMovimiento()) return;

  // getTotalLength no existe en todos lados —jsdom, por ejemplo— y si falla no
  // vale la pena romper el gráfico entero por una animación.
  let largo;
  try {
    largo = trazo.getTotalLength();
  } catch {
    return;
  }
  if (!Number.isFinite(largo) || largo === 0) return;

  trazo.style.strokeDasharray = String(largo);
  trazo.style.strokeDashoffset = String(largo);

  // Dos rAF y no uno: con uno solo, el navegador puede juntar el estilo inicial
  // y el final en el mismo cuadro y no transicionar nada. El segundo garantiza
  // que el estado de partida ya se pintó.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      trazo.style.transition = `stroke-dashoffset ${duracion}ms var(--curva)`;
      trazo.style.strokeDashoffset = "0";
    });
  });
}

/**
 * Suelta un valor recién en el cuadro siguiente, para que una transición CSS
 * tenga desde dónde salir.
 *
 * Lo usan la dona y el medidor: los dos se dibujan en cero y el valor real entra
 * después, que es lo que convierte un atributo escrito en una animación.
 */
export function enElProximoCuadro(hacer) {
  requestAnimationFrame(() => requestAnimationFrame(hacer));
}
