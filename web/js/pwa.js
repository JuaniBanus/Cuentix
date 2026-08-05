// Registro del service worker.
//
// Sin esto la app funciona igual: lo que se pierde es poder instalarla y abrirla
// sin internet. Por eso todo el registro va envuelto y no puede tumbar el
// arranque.

export function registrarServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  // El navegador solo acepta service workers en HTTPS (o en localhost). Abierto
  // como archivo suelto no hay registro, y no es un error: es lo esperado.
  if (location.protocol === "file:") return;

  // Después de load: registrarlo antes compite por ancho de banda con la
  // primera pintada de la app.
  addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((error) => {
      console.warn("No se pudo registrar el service worker:", error.message);
    });
  });
}
