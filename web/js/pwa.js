// Registro del service worker.

export function registrarServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  if (location.protocol === "file:") return;

  addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((error) => {
      console.warn("No se pudo registrar el service worker:", error.message);
    });
  });
}
