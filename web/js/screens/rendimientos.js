// Panel "Dónde rinde más tu plata", dentro de Ahorros.
//
// Va arriba del patrimonio en dólares y debajo del análisis del dólar, y el
// orden tiene sentido de lectura: primero en qué moneda conviene estar, después
// dónde poner los pesos que quedan, y al final cuánto se tiene en total.
//
// TRES DECISIONES QUE NO SON OBVIAS
//
// 1. La fecha del dato se muestra SIEMPRE, no solo cuando está vieja. Estas
//    tasas las refresca un cron contra una API de terceros; el día que esa
//    fuente cambie, lo único que va a delatar el problema es una fecha que dejó
//    de moverse. Escondida atrás de un tooltip no la mira nadie.
//
// 2. El simulador NO repinta la pantalla. Escribir un monto solo reescribe los
//    números de la tabla: si pasara por el estado global y `pintar()`, el input
//    perdería el foco en cada tecla y no se podría escribir.
//
// 3. El tope de monto se aplica de verdad. Si una billetera paga hasta $750.000
//    y el usuario simula dos millones, la ganancia se calcula sobre el tope y se
//    avisa. Mostrar el rendimiento pleno sobre el excedente sería un número
//    lindo y mentiroso, que es exactamente lo que un comparador no puede hacer.

// `monto` tapa sola las cifras cuando el ojo está cerrado, y las convierte si
// está activo el "ver en dólares": por eso las ganancias simuladas pasan por
// ella y no por un toLocaleString propio.
import { esc, monto } from "../format.js";

// Con cuánto arranca el simulador antes de que el usuario toque nada. Redondo y
// del orden de magnitud de un sueldo: sirve para leer la tabla de un vistazo.
const MONTO_INICIAL = 100000;

// A partir de acá las tasas dejan de ser "de hoy" y se avisa en pantalla. Una
// semana tolera un finde largo y una corrida perdida sin dar un falso positivo.
const DIAS_PARA_AVISAR = 7;

const ETIQUETA_TIPO = {
  fci: "Fondo común",
  cuenta_remunerada: "Cuenta remunerada",
};

/** Los días que pasaron desde una fecha ISO. null si no se puede leer. */
function diasDesde(iso, hoy) {
  const cuando = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(cuando.getTime())) return null;
  const referencia = new Date(`${hoy}T00:00:00`);
  if (Number.isNaN(referencia.getTime())) return null;
  return Math.floor((referencia - cuando) / 86400000);
}

function fechaLarga(iso) {
  const cuando = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(cuando.getTime())) return iso;
  return cuando.toLocaleDateString("es-AR", { day: "numeric", month: "long", year: "numeric" });
}

function pct(valor) {
  // El ojo que oculta los montos no tapa las tasas: una TNA es información
  // pública, no dice cuánta plata tiene el usuario. Sí se tapan las ganancias
  // simuladas, que salen de un monto que él escribió.
  return `${valor.toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

/**
 * Lo que rinde un capital a esa TNA.
 *
 * La TNA es nominal anual con capitalización a 30 días, así que el mes es
 * TNA/12 —no (1+TNA)^(1/12), que sería pasar de una tasa efectiva—. Es el mismo
 * criterio que usa el backend en app/tasas.py, para que el bot y la web no
 * contesten distinto sobre el mismo número.
 *
 * El año se calcula CON reinversión: dejar la plata quieta doce meses en una
 * cuenta que capitaliza es lo que efectivamente pasa si no la tocás, y la suma
 * simple subestimaría la diferencia entre la primera y la última de la tabla.
 */
function ganancia(capital, tna) {
  const mensual = tna / 100 / 12;
  return {
    mes: capital * mensual,
    anio: capital * ((1 + mensual) ** 12 - 1),
  };
}

function filaTabla(fila, capital) {
  const tna = Number(fila.tna);
  if (!Number.isFinite(tna)) return "";

  const tope = fila.tope_monto == null ? null : Number(fila.tope_monto);
  const tieneTope = tope !== null && Number.isFinite(tope) && tope > 0;
  // Sobre el excedente del tope estas cuentas no pagan nada, así que rinde el
  // tope y no el capital.
  const base = tieneTope ? Math.min(capital, tope) : capital;
  const excedido = tieneTope && capital > tope;

  const { mes, anio } = ganancia(base, tna);

  return `
    <li class="rend-fila">
      <div class="rend-quien">
        <span class="rend-nombre">${esc(fila.nombre)}</span>
        <span class="rend-tipo">${esc(ETIQUETA_TIPO[fila.tipo] ?? fila.tipo)}</span>
        ${excedido
          ? `<span class="rend-aviso-tope">paga solo hasta ${monto(tope, "ARS")}</span>`
          : tieneTope
            ? `<span class="rend-tope">tope ${monto(tope, "ARS")}</span>`
            : ""}
      </div>
      <span class="rend-tna">${pct(tna)}<span class="rend-tna-nota">TNA</span></span>
      <span class="rend-gana">
        <span class="rend-gana-mes">${monto(mes, "ARS")}</span>
        <span class="rend-gana-anio">${monto(anio, "ARS")} al año</span>
      </span>
    </li>`;
}

/** Reescribe solo las filas. Se llama en cada tecla del simulador. */
function pintarFilas(lista, filas, capital) {
  lista.innerHTML = filas.map((f) => filaTabla(f, capital)).join("");
}

/**
 * @param {HTMLElement} contenedor
 * @param {{rendimientos: Array, hoy: string}} ctx
 */
export function renderRendimientos(contenedor, { rendimientos, hoy }) {
  const seccion = document.createElement("section");
  seccion.className = "tarjeta rend";

  // Sin datos no se dibuja una tarjeta vacía, pero tampoco se calla: la tabla
  // se llena sola con un cron, así que "no hay nada" casi siempre significa
  // "todavía no corrió" o "se rompió", y las dos merecen una explicación.
  if (!rendimientos?.length) {
    seccion.innerHTML = `
      <h2 class="tarjeta-titulo">💰 Dónde rinde más tu plata</h2>
      <p class="vacio">
        Todavía no tengo las tasas de las billeteras.<br>
        Las actualiza un proceso automático una vez por día; el resto de la
        pantalla funciona igual.
      </p>`;
    contenedor.append(seccion);
    return;
  }

  // Ya vienen ordenadas por TNA desde la base, pero el orden es lo único que
  // hace que esta tabla signifique algo: se reordena acá para no depender de
  // que la consulta conserve el `order`.
  const filas = [...rendimientos]
    .filter((f) => Number.isFinite(Number(f.tna)))
    .sort((a, b) => Number(b.tna) - Number(a.tna));

  // La MÁS VIEJA de todas, no la más nueva: si una sola quedó atrasada, el
  // conjunto está atrasado. Quedarse con la más fresca sería tapar justo el
  // caso que esta fecha existe para detectar.
  const fechas = filas.map((f) => f.fecha_actualizacion).filter(Boolean).sort();
  const masVieja = fechas[0] ?? null;
  const atraso = masVieja ? diasDesde(masVieja, hoy) : null;
  const vieja = atraso !== null && atraso > DIAS_PARA_AVISAR;

  seccion.innerHTML = `
    <h2 class="tarjeta-titulo">💰 Dónde rinde más tu plata</h2>

    <p class="rend-fecha ${vieja ? "es-vieja" : ""}">
      ${masVieja
        ? `${vieja ? "⚠️" : "📅"} Tasas al <strong>${esc(fechaLarga(masVieja))}</strong>${
            atraso === 0 ? " · de hoy" : atraso === 1 ? " · de ayer" : ` · hace ${atraso} días`
          }`
        : "📅 Sin fecha de actualización"}
    </p>
    ${vieja
      ? `<p class="apunte rend-alerta">
           Hace más de ${DIAS_PARA_AVISAR} días que no se actualizan: puede que la
           fuente esté caída. Verificá en la app de tu billetera antes de mover plata.
         </p>`
      : ""}

    <div class="rend-simulador">
      <label class="rend-label" for="rend-monto">Si pongo</label>
      <div class="rend-input-grupo">
        <span class="rend-signo">$</span>
        <input id="rend-monto" class="rend-input" type="number" inputmode="numeric"
               min="0" step="10000" value="${MONTO_INICIAL}"
               aria-label="Monto a simular, en pesos">
      </div>
      <span class="rend-label rend-label-fin">gano por mes</span>
    </div>

    <ul class="rend-tabla" id="rend-tabla"></ul>

    <p class="apunte rend-nota">
      Rendimientos variables y no garantizados: la mayoría sale de un fondo común
      de dinero y la tasa cambia todos los días. La ganancia anual supone dejar la
      plata quieta y reinvertir. Datos públicos de la CAFCI vía argentinadatos.
    </p>`;

  contenedor.append(seccion);

  const lista = seccion.querySelector("#rend-tabla");
  const input = seccion.querySelector("#rend-monto");

  const refrescar = () => {
    // Un input vacío o con basura vale cero, no NaN: la tabla tiene que seguir
    // ahí mientras el usuario borra para escribir otro número.
    const capital = Math.max(0, Number(input.value) || 0);
    pintarFilas(lista, filas, capital);
  };

  refrescar();
  input.addEventListener("input", refrescar);
}
