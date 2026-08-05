// Genera los íconos de la PWA. Se corre a mano: node tools/generar_iconos.mjs
//
// Los PNG están versionados en web/icons/, pero el generador va al repo igual
// para que se puedan rehacer si cambia la marca, sin depender de que alguien
// tenga el archivo de diseño.
//
// El dibujo es el mismo anillo de la dona de gastos, con el corte a la derecha:
// lee como gráfico de finanzas y como la C de Cuentix al mismo tiempo. Sin
// dependencias: el PNG se arma acá con zlib, que ya viene con Node.

import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const DESTINO = join(RAIZ, "web", "icons");

const FONDO = [0x16, 0x18, 0x26]; // --fondo del tema oscuro
const TRAZO = [0x91, 0x84, 0xd9]; // --acento, el violeta de marca

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

// ------------------------------------------------------------- El dibujo

const MUESTRAS = 4; // supermuestreo por eje: 16 por píxel, suficiente para bordes limpios

/** ¿El punto cae dentro del anillo? Devuelve 1 o 0. */
function enAnillo(x, y, { centro, radio, grosor, corte }) {
  const dx = x - centro;
  const dy = y - centro;
  const distancia = Math.hypot(dx, dy);
  if (Math.abs(distancia - radio) > grosor / 2) return 0;

  // El corte mira a la derecha (ángulo 0) y es lo que convierte el anillo en C.
  const angulo = Math.abs(Math.atan2(dy, dx));
  return angulo < corte / 2 ? 0 : 1;
}

/** ¿El punto cae dentro del cuadrado de esquinas redondeadas? */
function enPlaca(x, y, { lado, esquina }) {
  const dx = Math.max(esquina - x, 0, x - (lado - esquina));
  const dy = Math.max(esquina - y, 0, y - (lado - esquina));
  return Math.hypot(dx, dy) <= esquina ? 1 : 0;
}

/**
 * @param {number} lado
 * @param {{maskable?: boolean}} opciones  maskable = a sangre y con el anillo
 *   más chico, para que Android pueda recortarlo en cualquier forma sin comerse
 *   parte del dibujo (la zona segura es el 80% central).
 */
function dibujar(lado, { maskable = false } = {}) {
  const anillo = {
    centro: lado / 2,
    radio: lado * (maskable ? 0.245 : 0.315),
    grosor: lado * (maskable ? 0.092 : 0.118),
    corte: (55 * Math.PI) / 180,
  };
  const placa = { lado, esquina: maskable ? 0 : lado * 0.22 };

  const pixeles = new Uint8Array(lado * lado * 4);

  for (let y = 0; y < lado; y++) {
    for (let x = 0; x < lado; x++) {
      let dentroPlaca = 0;
      let dentroAnillo = 0;

      for (let sy = 0; sy < MUESTRAS; sy++) {
        for (let sx = 0; sx < MUESTRAS; sx++) {
          const px = x + (sx + 0.5) / MUESTRAS;
          const py = y + (sy + 0.5) / MUESTRAS;
          dentroPlaca += maskable ? 1 : enPlaca(px, py, placa);
          dentroAnillo += enAnillo(px, py, anillo);
        }
      }

      const total = MUESTRAS * MUESTRAS;
      const alfaPlaca = dentroPlaca / total;
      const alfaAnillo = (dentroAnillo / total) * alfaPlaca;

      // El violeta se mezcla sobre el fondo, y el fondo sobre transparente. El
      // PNG guarda color sin premultiplicar, así que se divide por el alfa
      // final: sin eso el borde redondeado sale con una orla oscura.
      const mezcla = (canal) =>
        alfaPlaca === 0
          ? 0
          : Math.round(
              (TRAZO[canal] * alfaAnillo + FONDO[canal] * (alfaPlaca - alfaAnillo)) / alfaPlaca
            );

      const i = (y * lado + x) * 4;
      pixeles[i] = mezcla(0);
      pixeles[i + 1] = mezcla(1);
      pixeles[i + 2] = mezcla(2);
      pixeles[i + 3] = Math.round(alfaPlaca * 255);
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
