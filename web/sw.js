// Service worker de Cuentix.
//
// Hace dos cosas: que la app se pueda instalar, y que abra aunque no haya
// internet (con el aviso de conexión adentro, en vez del dinosaurio del
// navegador).
//
// Estrategia a propósito conservadora:
//
//   - Lo propio (HTML, CSS, JS) va por RED PRIMERO, y el caché es el paracaídas.
//     Al revés —caché primero— es más rápido, pero cada deploy quedaría invisible
//     hasta que alguien se acuerde de subir la VERSION de acá abajo. En una app
//     que todavía cambia todas las semanas, eso se paga caro.
//   - Lo de terceros (la tipografía y el cliente de Supabase, ambos con la
//     versión en la URL) va por CACHÉ PRIMERO: nunca cambian bajo el mismo
//     nombre y son lo más pesado de bajar.
//   - Supabase NO se cachea nunca. Son datos privados y con token: guardarlos
//     en el disco del navegador sería filtrarlos.
//
// Subir VERSION borra el caché viejo. Hay que tocarla solo si cambia esta lista.

const VERSION = "cuentix-v9";

const ESENCIALES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./css/styles.css",
  "./js/app.js",
  "./js/auth.js",
  "./js/aviso.js",
  "./js/config.js",
  "./js/cotizaciones.js",
  "./js/cuentas.js",
  "./js/data.js",
  "./js/donut.js",
  "./js/estado.js",
  "./js/format.js",
  "./js/gastosCuentas.js",
  "./js/gauge.js",
  "./js/insights.js",
  "./js/linea.js",
  "./js/objetivos.js",
  "./js/periodo.js",
  "./js/precios.js",
  "./js/pwa.js",
  "./js/router.js",
  "./js/salud.js",
  "./js/selectorPeriodo.js",
  "./js/tema.js",
  "./js/screens/ahorros.js",
  "./js/screens/comunes.js",
  "./js/screens/gastos.js",
  "./js/screens/inicio.js",
  "./js/screens/inversiones.js",
  "./js/screens/objetivos.js",
  "./js/screens/porTipo.js",
  "./js/screens/usuario.js",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(ESENCIALES)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((nombres) => Promise.all(nombres.filter((n) => n !== VERSION).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

/** Terceros con la versión escrita en la URL: se pueden guardar sin miedo. */
function esDeTerceroEstable(url) {
  return (
    url.hostname === "fonts.googleapis.com" ||
    url.hostname === "fonts.gstatic.com" ||
    url.hostname === "cdn.jsdelivr.net"
  );
}

async function redPrimero(pedido) {
  const cache = await caches.open(VERSION);
  try {
    const respuesta = await fetch(pedido);
    // Solo se guarda lo que salió bien: cachear un 404 lo dejaría pegado.
    if (respuesta.ok) cache.put(pedido, respuesta.clone());
    return respuesta;
  } catch (error) {
    const guardado = await cache.match(pedido);
    if (guardado) return guardado;
    // Navegar sin red: se devuelve el HTML y la app muestra su propio aviso.
    if (pedido.mode === "navigate") {
      const shell = await cache.match("./index.html");
      if (shell) return shell;
    }
    throw error;
  }
}

async function cachePrimero(pedido) {
  const cache = await caches.open(VERSION);
  const guardado = await cache.match(pedido);
  if (guardado) return guardado;

  const respuesta = await fetch(pedido);
  if (respuesta.ok || respuesta.type === "opaque") cache.put(pedido, respuesta.clone());
  return respuesta;
}

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  if (pedido.method !== "GET") return;

  const url = new URL(pedido.url);

  // Todo lo que va a Supabase pasa de largo: sin caché y sin intermediarios.
  if (url.hostname.endsWith(".supabase.co")) return;

  if (esDeTerceroEstable(url)) {
    evento.respondWith(cachePrimero(pedido));
    return;
  }

  if (url.origin === self.location.origin) {
    evento.respondWith(redPrimero(pedido));
  }
});
