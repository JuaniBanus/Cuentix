-- Recordatorio diario: "¿Cómo fue tu día? Contame lo que gastaste."

create table if not exists public.recordatorios (
    chat_id      bigint        primary key,

    user_id      uuid          references auth.users (id) on delete cascade,

    hora         smallint      not null check (hora between 0 and 23),

    zona_horaria text          not null default 'America/Argentina/Buenos_Aires',

    activo       boolean       not null default true,

    ultimo_envio date,

    created_at   timestamptz   not null default now(),
    updated_at   timestamptz   not null default now()
);

create index if not exists recordatorios_activos_idx
    on public.recordatorios (activo) where activo;

alter table public.recordatorios enable row level security;

drop policy if exists "recordatorios: leer los propios" on public.recordatorios;

create policy "recordatorios: leer los propios"
    on public.recordatorios for select
    to authenticated
    using (auth.uid() = user_id);

select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'recordatorios';
