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

// Dónde vive el bot. Se usa solo para el panel de Insights de Gastos: es el
// único pedido que la web no le hace directo a Supabase.
//
// Tiene que ser el backend porque el análisis lo hace Gemini, y la clave de
// Gemini no puede estar acá por lo mismo que no puede estar la service_role.
// La web manda números ya agregados y recibe el texto; la clave nunca sale
// del servidor.
//
// En Render el dominio es https://<nombre-del-servicio>.onrender.com.
// Vacío = el panel queda desactivado y lo dice en pantalla, sin romper nada.
export const BACKEND_URL = "https://cuentix-bot.onrender.com";

export const SUPABASE_URL = "https://jyzvpakixjydvspwuexv.supabase.co";

export const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp5enZwYWtpeGp5ZHZzcHd1ZXh2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2MTUyMjUsImV4cCI6MjEwMTE5MTIyNX0.jUQA4KCLBgH0_MF1xurYwj-ezHiyTBgmirKtx1mX2-E";
