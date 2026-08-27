-- Tabla de tenencias de inversión. La escribe el BOT (service_role), la lee la

create table if not exists public.inversiones (
    id            uuid          primary key default gen_random_uuid(),

    user_id       uuid          not null default auth.uid()
                                references auth.users (id) on delete cascade,

    tipo          text          not null
                  check (tipo in ('accion', 'etf', 'bono', 'cedear',
                                  'fci', 'cripto', 'plazo_fijo')),

    ticker        text          check (ticker is null or char_length(ticker) between 1 and 20),
    nombre        text          not null check (char_length(nombre) between 1 and 120),

    cantidad      numeric(24,8) not null check (cantidad > 0),
    precio_compra numeric(24,8) not null check (precio_compra >= 0),

    moneda        text          not null default 'USD'
                  check (moneda in ('ARS', 'USD', 'EUR')),

    fecha_compra  date          not null default current_date,
    sector        text          check (sector is null or char_length(sector) <= 60),

    created_at    timestamptz   not null default now()
);

create index if not exists inversiones_user_idx    on public.inversiones (user_id);
create index if not exists inversiones_fecha_idx   on public.inversiones (user_id, fecha_compra desc);
create index if not exists inversiones_tipo_idx    on public.inversiones (user_id, tipo);

alter table public.inversiones enable row level security;

drop policy if exists "inversiones: leer las propias" on public.inversiones;

create policy "inversiones: leer las propias"
    on public.inversiones
    for select
    to authenticated
    using (auth.uid() = user_id);

select policyname, cmd, roles, qual
from pg_policies
where schemaname = 'public' and tablename = 'inversiones';
