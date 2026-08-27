// Cambio obligatorio de contraseña.

const MINIMO = 8;

/** Engancha el formulario. */
export function montarPassword(alCambiar) {
  const form = document.querySelector("#form-password");
  const error = document.querySelector("#password-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = form.querySelector("button");
    const nueva = form.password.value;
    const repetida = form.repetir.value;

    error.textContent = "";

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
