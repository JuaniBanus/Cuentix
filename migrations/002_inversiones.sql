-- Tabla de tenencias de inversión. La escribe el BOT (service_role), la lee la
-- WEB (anon key + sesión del usuario).
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

create table if not exists public.inversiones (
    id            uuid          primary key default gen_random_uuid(),

    -- Dueño de la tenencia. El default auth.uid() solo se completa solo cuando
    -- el INSERT viaja con el JWT de un usuario logueado; el bot escribe con
    -- service_role, donde auth.uid() es NULL, así que TIENE que mandar el
    -- user_id explícito. Por eso la columna es not null: si el bot se lo
    -- olvida, el insert falla en vez de crear una fila huérfana que nadie
    -- podría leer nunca (ninguna policy la haría visible).
    user_id       uuid          not null default auth.uid()
                                references auth.users (id) on delete cascade,

    tipo          text          not null
                  check (tipo in ('accion', 'etf', 'bono', 'cedear',
                                  'fci', 'cripto', 'plazo_fijo')),

    -- En mayúsculas y sin espacios (AAPL, BTC, AL30). Un plazo fijo puede no
    -- tener ticker, de ahí que sea opcional.
    ticker        text          check (ticker is null or char_length(ticker) between 1 and 20),
    nombre        text          not null check (char_length(nombre) between 1 and 120),

    -- numeric y no float: 0.00000001 BTC tiene que sobrevivir intacto.
    -- 8 decimales es el estándar de cripto; las acciones usan muchos menos.
    cantidad      numeric(24,8) not null check (cantidad > 0),
    precio_compra numeric(24,8) not null check (precio_compra >= 0),

    -- Default USD y no ARS como en movimientos: las tenencias se cotizan
    -- casi siempre en dólares. Los tres códigos son los de Moneda (app/models.py).
    moneda        text          not null default 'USD'
                  check (moneda in ('ARS', 'USD', 'EUR')),

    fecha_compra  date          not null default current_date,
    sector        text          check (sector is null or char_length(sector) <= 60),

    created_at    timestamptz   not null default now()
);

-- La web filtra siempre por usuario; el índice evita el scan completo cuando la
-- tabla crezca. Los otros dos son para ordenar y agrupar en las pantallas.
create index if not exists inversiones_user_idx    on public.inversiones (user_id);
create index if not exists inversiones_fecha_idx   on public.inversiones (user_id, fecha_compra desc);
create index if not exists inversiones_tipo_idx    on public.inversiones (user_id, tipo);

-- ------------------------------------------------------------------ RLS ----
-- Sin esto, la anon key puede leer y escribir la tabla entera desde el
-- navegador: PostgREST expone todo lo que RLS no proteja.
alter table public.inversiones enable row level security;

-- Idempotencia: create policy no admite "if not exists" en todas las versiones.
drop policy if exists "inversiones: leer las propias" on public.inversiones;

-- ÚNICA policy: leer, y solo las filas propias. No hay policy de INSERT,
-- UPDATE ni DELETE, así que desde la web esas operaciones se rechazan aunque
-- alguien edite el JavaScript: lo que no está permitido, está prohibido.
create policy "inversiones: leer las propias"
    on public.inversiones
    for select
    to authenticated              -- excluye a los visitantes sin login
    using (auth.uid() = user_id);

-- Verificación: tiene que listar una sola policy, SELECT, para authenticated.
select policyname, cmd, roles, qual
from pg_policies
where schemaname = 'public' and tablename = 'inversiones';
