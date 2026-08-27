// Pantalla de login: formulario, errores y estado del botón.

import { entrar } from "./data.js";

/** Engancha el formulario. */
export function montarLogin(alEntrar) {
  const form = document.querySelector("#form-login");
  const error = document.querySelector("#login-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = form.querySelector("button");

    error.textContent = "";
    boton.disabled = true;
    boton.textContent = "Entrando…";

    try {
      const sesion = await entrar(form.email.value.trim(), form.password.value);
      form.password.value = "";
      await alEntrar(sesion);
    } catch (err) {
      error.textContent = err.message;
      form.password.focus();
      form.password.select();
    } finally {
      boton.disabled = false;
      boton.textContent = "Entrar";
    }
  });
}

/** Deja el login limpio y con el foco puesto, para entrar o para volver a entrar. */
export function enfocarLogin() {
  const form = document.querySelector("#form-login");
  document.querySelector("#login-error").textContent = "";
  form.password.value = "";
  form.email.focus();
}
