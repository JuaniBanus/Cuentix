-- Alertas de precio: "avisame si AAPL baja 5%".

create table if not exists public.alertas (
    id             uuid          primary key default gen_random_uuid(),

    user_id        uuid          not null default auth.uid()
                                 references auth.users (id) on delete cascade,

    chat_id        bigint        not null,

    ticker         text          not null check (char_length(ticker) between 1 and 20),
    mercado        text          not null default 'us' check (mercado in ('us', 'ar')),

    tipo           text          not null
                                 check (tipo in ('baja', 'sube', 'debajo', 'encima')),

    umbral         numeric(18,6) not null check (umbral > 0),

    referencia     numeric(18,6),
    moneda         text          check (moneda is null or char_length(moneda) = 3),

    activa         boolean       not null default true,
    disparada_en   timestamptz,
    precio_disparo numeric(18,6),

    created_at     timestamptz   not null default now()
);

create index if not exists alertas_activas_idx
    on public.alertas (activa) where activa;
create index if not exists alertas_user_idx on public.alertas (user_id);

alter table public.alertas enable row level security;

drop policy if exists "alertas: leer las propias" on public.alertas;
drop policy if exists "alertas: borrar las propias" on public.alertas;

create policy "alertas: leer las propias"
    on public.alertas for select
    to authenticated
    using (auth.uid() = user_id);

create policy "alertas: borrar las propias"
    on public.alertas for delete
    to authenticated
    using (auth.uid() = user_id);

select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'alertas';
