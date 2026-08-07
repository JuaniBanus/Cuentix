// Genera los íconos de la PWA. Se corre a mano: node tools/generar_iconos.mjs
//
// Los PNG están versionados en web/icons/, pero el generador va al repo igual
// para que se puedan rehacer si cambia la marca, sin depender de que alguien
// tenga el archivo de diseño.
//
// El dibujo es la C de Cuentix —un anillo abierto a la derecha, con puntas
// redondeadas— y adentro tres barras que suben. Lee como la inicial y como un
// gráfico de finanzas al mismo tiempo. Sin dependencias: el PNG se arma acá con
// zlib, que ya viene con Node.

import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const DESTINO = join(RAIZ, "web", "icons");

// La placa no usa --fondo del tema: sobre el fondo casi negro de la app el
// ícono desaparecería entre los demás del launcher. Va el teal de marca, que
// es lo que lo hace reconocible de lejos.
const PLACA = [0x0d, 0x6d, 0x7e];
const TRAZO = [0xff, 0xff, 0xff];
// Las barras van de menta a blanco, de la más baja a la más alta: el degradé
// es lo que da la sensación de que la serie crece.
const BARRAS = [
  [0x9b, 0xd9, 0xc7],
  [0x56, 0xc6, 0xa9],
  [0xff, 0xff, 0xff],
];

// --------------------------------------------------------------- PNG crudo

const TABLA_CRC = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = TABLA_CRC[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function trozo(tipo, datos) {
  const largo = Buffer.alloc(4);
  largo.writeUInt32BE(datos.length);
  const cuerpo = Buffer.concat([Buffer.from(tipo, "ascii"), datos]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(cuerpo));
  return Buffer.concat([largo, cuerpo, crc]);
}

/** @param {Uint8Array} pixeles RGBA, lado*lado*4 */
function png(pixeles, lado) {
  const cabecera = Buffer.alloc(13);
  cabecera.writeUInt32BE(lado, 0);
  cabecera.writeUInt32BE(lado, 4);
  cabecera[8] = 8;  // bits por canal
  cabecera[9] = 6;  // RGBA
  // Cada fila arranca con un byte de filtro; 0 = sin filtrar.
  const crudo = Buffer.alloc(lado * (lado * 4 + 1));
  for (let y = 0; y < lado; y++) {
    crudo[y * (lado * 4 + 1)] = 0;
    Buffer.from(pixeles.buffer, y * lado * 4, lado * 4).copy(
      crudo, y * (lado * 4 + 1) + 1
    );
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    trozo("IHDR", cabecera),
    trozo("IDAT", deflateSync(crudo, { level: 9 })),
    trozo("IEND", Buffer.alloc(0)),
  ]);
}

// ------------------------------------------------------------- Las formas
// Todo se mide en fracción del lado, así el mismo dibujo sale idéntico en 180
// y en 512. Cada función contesta sí o no para un punto; el antialias sale de
// preguntar muchas veces por píxel, más abajo.

/** Cuadrado de esquinas redondeadas. */
function enPlaca(x, y, { lado, esquina }) {
  const dx = Math.max(esquina - x, 0, x - (lado - esquina));
  const dy = Math.max(esquina - y, 0, y - (lado - esquina));
  return Math.hypot(dx, dy) <= esquina;
}

/** Anillo abierto a la derecha, con las dos puntas redondeadas. */
function enAnillo(x, y, { centro, radio, grosor, corte, puntas }) {
  const dx = x - centro;
  const dy = y - centro;

  // Las puntas primero: son el semicírculo que sobresale del corte, así que
  // sin ellas la C terminaría en dos filos rectos.
  for (const p of puntas) {
    if (Math.hypot(x - p.x, y - p.y) <= grosor / 2) return true;
  }

  if (Math.abs(Math.hypot(dx, dy) - radio) > grosor / 2) return false;
  // El corte mira a la derecha (ángulo 0) y es lo que convierte el anillo en C.
  return Math.abs(Math.atan2(dy, dx)) >= corte / 2;
}

/** Barra vertical con las dos puntas redondeadas (una cápsula). */
function enBarra(x, y, { cx, base, altura, ancho }) {
  const r = ancho / 2;
  // Los centros de los dos semicírculos; entre ellos la cápsula es un rectángulo.
  const arriba = base - altura + r;
  const abajo = base - r;
  const dy = y < arriba ? y - arriba : y > abajo ? y - abajo : 0;
  return Math.hypot(x - cx, dy) <= r;
}

// -------------------------------------------------------------- El dibujo

const MUESTRAS = 6; // por eje: 36 por píxel. Las barras son finas y el ojo ve el escalón.

/**
 * @param {number} lado
 * @param {{maskable?: boolean}} opciones  maskable = a sangre y con el dibujo
 *   más chico, para que Android pueda recortarlo en cualquier forma sin comerse
 *   parte del logo (la zona segura es el 80% central).
 */
function dibujar(lado, { maskable = false } = {}) {
  // Un solo factor encoge todo junto: si se tocaran los números de a uno, las
  // barras dejarían de caer donde caen respecto del anillo.
  const k = (maskable ? 0.78 : 1) * lado;
  const centro = lado / 2;

  const corte = (76 * Math.PI) / 180;
  const radio = 0.189 * k;
  const grosor = 0.078 * k;

  const anillo = {
    centro,
    radio,
    grosor,
    corte,
    puntas: [-corte / 2, corte / 2].map((a) => ({
      x: centro + radio * Math.cos(a),
      y: centro + radio * Math.sin(a),
    })),
  };

  const ancho = 0.046 * k;
  const base = centro + 0.113 * k;
  const barras = [0.0625, 0.125, 0.19].map((altura, i) => ({
    cx: centro + (i - 1) * 0.079 * k,
    base,
    altura: altura * k,
    ancho,
  }));

  const placa = { lado, esquina: maskable ? 0 : lado * 0.22 };
  const pixeles = new Uint8Array(lado * lado * 4);
  const total = MUESTRAS * MUESTRAS;

  for (let y = 0; y < lado; y++) {
    for (let x = 0; x < lado; x++) {
      // Se acumula el color ya resuelto de cada submuestra en vez de mezclar
      // coberturas: así el color que se guarda es el de las submuestras que
      // realmente pintaron, y el borde redondeado no sale con orla.
      let opacas = 0;
      let r = 0, g = 0, b = 0;

      for (let sy = 0; sy < MUESTRAS; sy++) {
        for (let sx = 0; sx < MUESTRAS; sx++) {
          const px = x + (sx + 0.5) / MUESTRAS;
          const py = y + (sy + 0.5) / MUESTRAS;
          if (!maskable && !enPlaca(px, py, placa)) continue;

          const barra = barras.find((bar) => enBarra(px, py, bar));
          const color = barra
            ? BARRAS[barras.indexOf(barra)]
            : enAnillo(px, py, anillo)
              ? TRAZO
              : PLACA;

          opacas++;
          r += color[0];
          g += color[1];
          b += color[2];
        }
      }

      const i = (y * lado + x) * 4;
      if (opacas) {
        pixeles[i] = Math.round(r / opacas);
        pixeles[i + 1] = Math.round(g / opacas);
        pixeles[i + 2] = Math.round(b / opacas);
      }
      pixeles[i + 3] = Math.round((opacas / total) * 255);
    }
  }

  return png(pixeles, lado);
}

// ------------------------------------------------------------------ Salida

mkdirSync(DESTINO, { recursive: true });

const archivos = [
  ["icono-192.png", dibujar(192)],
  ["icono-512.png", dibujar(512)],
  ["icono-maskable-512.png", dibujar(512, { maskable: true })],
  // iOS ignora el manifest para el ícono: usa apple-touch-icon y no respeta
  // transparencia, así que va la placa completa.
  ["apple-touch-icon.png", dibujar(180)],
];

for (const [nombre, datos] of archivos) {
  writeFileSync(join(DESTINO, nombre), datos);
  console.log(`${nombre.padEnd(26)} ${(datos.length / 1024).toFixed(1)} KB`);
}
