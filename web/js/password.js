// Cambio obligatorio de contraseña.
//
// Mismo patrón que auth.js: engancha el formulario de una vista que ya está en
// el HTML, y no sabe nada de qué pasa después. Quién decide mostrarla es
// app.js, mirando `debe_cambiar_password` del perfil.
//
// Por qué es una vista entera y no un cartel arriba del dashboard: si el
// dashboard se dibuja, la contraseña provisoria ya sirvió para ver los datos, y
// el cartel pasa a ser una sugerencia. Mientras el flag esté puesto, no se
// dibuja nada.
//
// Con qué se prende el flag: no con el alta por invitación —ahí la persona
// elige su propia contraseña y no hay nada que cambiar, por eso el default de
// la columna pasó a false en migrations/014—, sino a mano, cuando le entregaste
// una contraseña que escribiste vos o después de un reseteo.

const MINIMO = 8;

/**
 * Engancha el formulario.
 *
 * @param {(nueva: string) => Promise<void>} alCambiar qué hacer con la nueva
 */
export function montarPassword(alCambiar) {
  const form = document.querySelector("#form-password");
  const error = document.querySelector("#password-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = form.querySelector("button");
    const nueva = form.password.value;
    const repetida = form.repetir.value;

    error.textContent = "";

    // Las dos comprobaciones que se pueden hacer sin molestar al servidor. La
    // de largo la repite Supabase; esta solo evita el viaje de ida y vuelta.
    if (nueva.length < MINIMO) {
      error.textContent = `Poné al menos ${MINIMO} caracteres.`;
      form.password.focus();
      return;
    }
    if (nueva !== repetida) {
      error.textContent = "Las dos no coinciden.";
      form.repetir.focus();
      form.repetir.select();
      return;
    }

    boton.disabled = true;
    boton.textContent = "Guardando…";

    try {
      await alCambiar(nueva);
      form.reset();
    } catch (err) {
      // El mensaje ya viene traducido desde data.js.
      error.textContent = err.message;
      form.password.focus();
    } finally {
      boton.disabled = false;
      boton.textContent = "Guardar y entrar";
    }
  });
}

/** Deja el formulario limpio y con el foco puesto. */
export function enfocarPassword() {
  const form = document.querySelector("#form-password");
  document.querySelector("#password-error").textContent = "";
  form.reset();
  form.password.focus();
}
