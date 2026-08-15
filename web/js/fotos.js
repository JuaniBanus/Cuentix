// Fotos de los objetivos, en Supabase Storage.
//
// EL BUCKET ES PRIVADO, no público. Son fotos de cosas que la persona quiere
// comprar —un auto, la casa, el viaje— y un bucket público las deja legibles
// para cualquiera que adivine la URL. Con bucket privado hay que pedir una URL
// firmada cada vez, que vence sola.
//
// Por eso en la base se guarda la RUTA y no la URL: una URL firmada guardada
// sería un link roto en unas horas.
//
// La ruta lleva el uuid del usuario adelante (<user_id>/<objetivo>.<ext>)
// porque las policies de Storage comparan ese primer tramo contra auth.uid().
// Sin esa convención, cualquiera con sesión podría leer las fotos de todos.

import { sb } from "./data.js";

const BUCKET = "objetivos";
// El bucket también lo limita del lado del servidor; acá se valida para poder
// avisar antes de subir 8 MB por una conexión de celular.
const TAMANO_MAXIMO = 5 * 1024 * 1024;
const TIPOS = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
// Las URLs firmadas duran lo suficiente para mirar la pantalla un rato.
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

/**
 * Sube la foto y devuelve su ruta dentro del bucket.
 *
 * El nombre del archivo lleva el id del objetivo y un sufijo temporal: sin el
 * sufijo, reemplazar la foto dejaría la anterior cacheada en el navegador y se
 * seguiría viendo la vieja.
 */
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
    // El caso más probable con RLS mal aplicado es un 403 sin detalle útil.
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
  // Se renueva antes de que venza, no cuando ya venció: si no, la imagen se
  // rompe justo mientras alguien la está mirando.
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

/** Borra la foto del bucket. Silencioso: si falla, queda un archivo huérfano. */
export async function borrar(ruta) {
  if (!ruta) return;
  _cacheFirmas.delete(ruta);
  try {
    await sb.storage.from(BUCKET).remove([ruta]);
  } catch {
    // Un archivo suelto en el bucket no rompe nada y no vale la pena
    // frenarle al usuario el guardado por esto.
  }
}
