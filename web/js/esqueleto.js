// Los huecos que ocupan los datos mientras se los busca.
//
// Un "Cargando…" en texto dice que algo está pasando y nada más. Un esqueleto
// dice además QUÉ está por llegar y CUÁNTO va a ocupar, y esa segunda parte es
// la que importa: cuando la respuesta entra, nada se corre de lugar. Sin esto,
// la pantalla pega un salto justo en el momento en que la persona empezó a leer.
//
// Por eso cada esqueleto de acá copia la estructura de la pantalla real y no es
// una grilla de rectángulos genéricos. Si alguna vez dejan de coincidir, el
// salto vuelve, y esa es la única razón por la que este archivo existe.

/** Un renglón de texto. `ancho` en porcentaje. */
const linea = (ancho = "100%", alto = 13) =>
  `<span class="esqueleto esqueleto-linea" style="width:${ancho}; height:${alto}px"></span>`;

/** La cabecera de una pantalla: el rótulo chiquito y la cifra grande debajo. */
function encabezado() {
  return `
    <section class="bloque">
      ${linea("38%", 11)}
      <span class="esqueleto esqueleto-cifra"></span>
      ${linea("52%", 12)}
    </section>`;
}

/** Una tarjeta con título y el cuerpo que se le pase. */
const tarjeta = (cuerpo) => `
  <section class="tarjeta">
    <span class="esqueleto esqueleto-titulo"></span>
    ${cuerpo}
  </section>`;

/** Filas de lista: avatar, dos renglones y el monto a la derecha. */
function filas(cuantas = 4) {
  return Array.from({ length: cuantas }, () => `
    <div class="esqueleto-fila">
      <span class="esqueleto esqueleto-avatar"></span>
      <span class="esqueleto-texto">
        <span class="esqueleto"></span>
        <span class="esqueleto"></span>
      </span>
      <span class="esqueleto esqueleto-monto"></span>
    </div>`).join("");
}

/** Barras por categoría: el nombre, el monto y el riel debajo. */
function barras(cuantas = 4) {
  // Los anchos bajan como bajaría un desglose real, que va de mayor a menor.
  // Todos iguales se leerían como una tabla vacía en vez de como datos en camino.
  const anchos = ["88%", "64%", "47%", "31%", "22%"];
  return `<div class="barras">
    ${Array.from({ length: cuantas }, (_, i) => `
      <div style="padding:7px 0; display:flex; flex-direction:column; gap:7px">
        ${linea(["42%", "35%", "50%", "38%", "44%"][i % 5], 12)}
        ${linea(anchos[i % anchos.length], 8)}
      </div>`).join("")}
  </div>`;
}

/**
 * El esqueleto de la carga inicial: es lo primero que ve alguien que entra, así
 * que copia la pantalla de Inicio, que es la que va a aparecer.
 */
export function esqueletoPantalla() {
  return `
    ${encabezado()}
    ${tarjeta(`<span class="esqueleto esqueleto-circulo" style="max-width:150px"></span>`)}
    ${tarjeta(`<span class="esqueleto esqueleto-circulo"></span>`)}
    <div class="grilla-2">
      <section class="tarjeta tarjeta-mini">${linea("55%", 11)}${linea("72%", 20)}</section>
      <section class="tarjeta tarjeta-mini">${linea("55%", 11)}${linea("72%", 20)}</section>
    </div>
    <section class="bloque">
      <span class="esqueleto esqueleto-titulo"></span>
      ${filas(4)}
    </section>`;
}

/** Inversiones: el valor de la cartera, los repartos y las posiciones. */
export function esqueletoInversiones() {
  return `
    ${encabezado()}
    ${tarjeta(`<span class="esqueleto esqueleto-circulo"></span>`)}
    ${tarjeta(barras(3))}
    <section class="bloque">
      <span class="esqueleto esqueleto-titulo"></span>
      ${filas(5)}
    </section>`;
}

/**
 * El gráfico de precio de un activo.
 *
 * Lleva la misma altura que el gráfico de verdad para que la tarjeta no cambie
 * de tamaño cuando llega el histórico.
 */
export function esqueletoPrecio() {
  return `
    <div class="precio-grafico">
      <div class="precio-cabecera">${linea("34%", 20)}${linea("22%", 13)}</div>
      <span class="esqueleto" style="height:120px; border-radius:var(--r-boton)"></span>
      <div class="precio-pie">${linea("18%", 11)}${linea("18%", 11)}</div>
    </div>`;
}

/**
 * Los insights.
 *
 * Este es el único que va acompañado de texto, y a propósito: los demás tardan
 * lo que tarda una consulta, pero este puede tardar un minuto entero si el
 * backend estaba dormido. Un esqueleto solo, latiendo sesenta segundos, se lee
 * como que se colgó.
 */
export function esqueletoInsights() {
  return `
    <div class="esqueleto-parrafo" role="status" aria-label="Analizando tus gastos">
      ${Array.from({ length: 3 }, () => `
        <div class="insight" style="border-bottom:0; padding:9px 0">
          <span class="esqueleto" style="width:20px; height:20px; border-radius:6px"></span>
          <span class="esqueleto-texto" style="display:flex; flex-direction:column; gap:7px">
            ${linea("46%", 13)}
            ${linea("92%", 11)}
          </span>
        </div>`).join("")}
    </div>
    <p class="esqueleto-nota">
      Analizando tus gastos… puede tardar hasta un minuto si el servidor estaba dormido.
    </p>`;
}
