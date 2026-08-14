-- Recordatorio diario: "¿Cómo fue tu día? Contame lo que gastaste."
--
-- Una fila por chat de Telegram. La escribe el BOT (service_role) cuando el
-- usuario corre /recordatorio; la web todavía no la toca, pero la policy de
-- lectura queda puesta para cuando la muestre.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

create table if not exists public.recordatorios (
    -- El chat de Telegram ES la identidad acá, y por eso es la clave primaria:
    -- un chat tiene un solo recordatorio diario. Con un id sintético habría que
    -- vigilar a mano que no se dupliquen, y dos filas para el mismo chat
    -- significarían dos mensajes cada noche.
    chat_id      bigint        primary key,

    -- Para que la web pueda mostrarlo. Nullable a propósito: el usuario puede
    -- configurar el recordatorio por Telegram sin tener cuenta en la web, y
    -- exigirlo dejaría al bot sin poder guardarlo.
    user_id      uuid          references auth.users (id) on delete cascade,

    -- Hora LOCAL del usuario, 0 a 23. Se guarda local y no en UTC porque es lo
    -- que la persona eligió: si algún día cambia la zona, "a las 21" tiene que
    -- seguir siendo a las 21 y no correrse tres horas.
    hora         smallint      not null check (hora between 0 and 23),

    -- Nombre IANA, no un offset. Argentina cambió de horario de verano varias
    -- veces; con un número fijo, el día que vuelva el DST los avisos llegan a
    -- la hora equivocada y nadie se acuerda de por qué.
    zona_horaria text          not null default 'America/Argentina/Buenos_Aires',

    activo       boolean       not null default true,

    -- Fecha LOCAL del último envío. Es lo que evita mandar dos veces el mismo
    -- día: el cron corre cada hora y puede repetirse o llegar tarde, así que no
    -- alcanza con "es la hora".
    ultimo_envio date,

    created_at   timestamptz   not null default now(),
    updated_at   timestamptz   not null default now()
);

-- El cron pide "los activos" cada hora: sin esto escanea la tabla entera.
create index if not exists recordatorios_activos_idx
    on public.recordatorios (activo) where activo;

-- ------------------------------------------------------------------ RLS ----
alter table public.recordatorios enable row level security;

drop policy if exists "recordatorios: leer los propios" on public.recordatorios;

-- Solo lectura, y solo lo propio. El bot escribe con service_role y saltea RLS;
-- desde el navegador no se puede crear ni modificar nada.
create policy "recordatorios: leer los propios"
    on public.recordatorios for select
    to authenticated
    using (auth.uid() = user_id);

-- Verificación: una policy, SELECT, para authenticated.
select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'recordatorios';
