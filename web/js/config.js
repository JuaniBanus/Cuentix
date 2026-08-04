// Conexión a Supabase.
//
// Estos dos valores NO son secretos: la anon key está pensada para vivir en el
// navegador y cualquiera puede leerla con Ctrl+U. Lo que protege los datos es
// la policy de RLS, que solo deja leer (y solo a usuarios logueados).
//
// La que nunca puede estar acá es la service_role / sb_secret_: esa saltea RLS
// y equivale a acceso total. Vive únicamente en el servidor, en el .env del bot.
//
// Dónde sacar la anon key: panel de Supabase -> Project Settings -> API Keys ->
// "anon public" (en los proyectos nuevos aparece como "publishable", sb_publishable_...).

export const SUPABASE_URL = "https://jyzvpakixjydvspwuexv.supabase.co";

export const SUPABASE_ANON_KEY = "PEGA_ACA_TU_ANON_KEY";
