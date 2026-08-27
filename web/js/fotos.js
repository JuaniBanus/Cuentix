// Fotos de los objetivos, en Supabase Storage.

import { sb } from "./data.js";

const BUCKET = "objetivos";
const TAMANO_MAXIMO = 5 * 1024 * 1024;
const TIPOS = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
const VIGENCIA_FIRMA = 60 * 60;

const _cacheFirmas = new Map();

/** Revisa el archivo antes de subirlo. Devuelve el problema, o null. */
export function revisar(archivo) {
  if (!archivo) return "No elegiste ninguna imagen.";
  if (!TIPOS.has(archivo.type)) return "Tiene que ser una imagen (JPG, PNG, WEBP o GIF).";
  if (archivo.size > TAMANO_MAXIMO) {
    return `La imagen pesa ${(archivo.size / 1024 / 1024).toFixed(1)} MB y el máximo son 5 MB.`;
  }
  return null;
}

/** Sube la foto y devuelve su ruta dentro del bucket. */
export async function subir(archivo, objetivoId) {
  const problema = revisar(archivo);
  if (problema) throw new Error(problema);

  const { data: sesion } = await sb.auth.getSession();
  const userId = sesion?.session?.user?.id;
  if (!userId) throw new Error("La sesión venció. Entrá de nuevo.");

  const extension = (archivo.name.split(".").pop() || "jpg").toLowerCase().slice(0, 5);
  const ruta = `${userId}/${objetivoId}-${Date.now()}.${extension}`;

  const { error } = await sb.storage.from(BUCKET).upload(ruta, archivo, {
    cacheControl: "3600",
    upsert: false,
  });

  if (error) {
    throw new Error(
      /policy|not authorized|row-level/i.test(error.message ?? "")
        ? "No pude guardar la imagen: falta correr la migración del bucket."
        : "No pude subir la imagen. Probá de nuevo."
    );
  }

  return ruta;
}

/** URL firmada para mostrar la foto. null si no hay o si falla. */
export async function url(ruta) {
  if (!ruta) return null;

  const guardada = _cacheFirmas.get(ruta);
  if (guardada && Date.now() < guardada.vence - 60_000) return guardada.url;

  const { data, error } = await sb.storage
    .from(BUCKET)
    .createSignedUrl(ruta, VIGENCIA_FIRMA);

  if (error || !data?.signedUrl) return null;

  _cacheFirmas.set(ruta, {
    url: data.signedUrl,
    vence: Date.now() + VIGENCIA_FIRMA * 1000,
  });
  return data.signedUrl;
}

/** Tira las URLs firmadas que haya en memoria. Se llama al cerrar sesión. */
export function olvidarFirmas() {
  _cacheFirmas.clear();
}

/** Borra la foto del bucket. Silencioso: si falla, queda un archivo huérfano. */
export async function borrar(ruta) {
  if (!ruta) return;
  _cacheFirmas.delete(ruta);
  try {
    await sb.storage.from(BUCKET).remove([ruta]);
  } catch {
  }
}
