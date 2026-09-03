// Service worker de Cuentix.

const VERSION = "cuentix-v20";

const ESENCIALES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./css/styles.css",
  "./js/animar.js",
  "./js/app.js",
  "./js/auth.js",
  "./js/aviso.js",
  "./js/barraSecciones.js",
  "./js/config.js",
  "./js/comparacion.js",
  "./js/cotizaciones.js",
  "./js/cuentas.js",
  "./js/data.js",
  "./js/dolar.js",
  "./js/donut.js",
  "./js/esqueleto.js",
  "./js/estado.js",
  "./js/format.js",
  "./js/fotos.js",
  "./js/gastosCuentas.js",
  "./js/gauge.js",
  "./js/insights.js",
  "./js/linea.js",
  "./js/mercado.js",
  "./js/narrativa.js",
  "./js/objetivos.js",
  "./js/pantalla.js",
  "./js/password.js",
  "./js/patrimonio.js",
  "./js/periodo.js",
  "./js/precioLinea.js",
  "./js/precios.js",
  "./js/pwa.js",
  "./js/recurrentes.js",
  "./js/router.js",
  "./js/salud.js",
  "./js/selectorPeriodo.js",
  "./js/tema.js",
  "./js/termometro.js",
  "./js/screens/admin.js",
  "./js/screens/ahorros.js",
  "./js/screens/comunes.js",
  "./js/screens/dolar.js",
  "./js/screens/gastos.js",
  "./js/screens/inicio.js",
  "./js/screens/inversiones.js",
  "./js/screens/narrativa.js",
  "./js/screens/objetivos.js",
  "./js/screens/porTipo.js",
  "./js/screens/retos.js",
  "./js/screens/patrimonio.js",
  "./js/screens/recurrentes.js",
  "./js/screens/rendimientos.js",
  "./js/screens/termometro.js",
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
    if (respuesta.ok) cache.put(pedido, respuesta.clone());
    return respuesta;
  } catch (error) {
    const guardado = await cache.match(pedido);
    if (guardado) return guardado;
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

  if (url.hostname.endsWith(".supabase.co")) return;

  if (esDeTerceroEstable(url)) {
    evento.respondWith(cachePrimero(pedido));
    return;
  }

  if (url.origin === self.location.origin) {
    evento.respondWith(redPrimero(pedido));
  }
});
