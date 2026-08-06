-- Alertas de precio: "avisame si AAPL baja 5%".
--
-- Las crea el usuario por Telegram y las revisa un cron cada tanto. Cuando un
-- umbral se cruza, el bot manda el mensaje.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

create table if not exists public.alertas (
    id             uuid          primary key default gen_random_uuid(),

    -- Mismo criterio que `inversiones`: el default auth.uid() no se completa
    -- cuando escribe el bot con service_role, así que el user_id viaja
    -- explícito. NOT NULL para que una alerta sin dueño no exista.
    user_id        uuid          not null default auth.uid()
                                 references auth.users (id) on delete cascade,

    -- A qué chat de Telegram avisar. No sale del user_id: la cuenta de la web
    -- y el chat del bot son dos identidades distintas, y el cron necesita esta
    -- para poder mandar el mensaje sin que haya nadie conectado.
    chat_id        bigint        not null,

    ticker         text          not null check (char_length(ticker) between 1 and 20),
    -- Dónde cotiza. El mismo ticker es dos activos distintos según el mercado
    -- (AAPL acción en NASDAQ, AAPL CEDEAR en BYMA), así que sin esto la alerta
    -- podría vigilar un papel que no es el que se quiso.
    mercado        text          not null default 'us' check (mercado in ('us', 'ar')),

    -- baja/sube: variación porcentual contra `referencia`.
    -- debajo/encima: el precio cruza un valor absoluto.
    tipo           text          not null
                                 check (tipo in ('baja', 'sube', 'debajo', 'encima')),

    -- Porcentaje para baja/sube, precio para debajo/encima. Siempre positivo:
    -- la dirección la da `tipo`, no el signo, así no hay dos formas de escribir
    -- lo mismo.
    umbral         numeric(18,6) not null check (umbral > 0),

    -- Precio al momento de crearla, contra el que se miden los porcentajes.
    -- Guardarlo es lo que hace que "baja 5%" signifique siempre lo mismo: 5%
    -- desde que la pediste, y no 5% desde una base que se mueve sola.
    referencia     numeric(18,6),
    moneda         text          check (moneda is null or char_length(moneda) = 3),

    -- Una alerta disparada se apaga en vez de repetirse. Sin esto, un papel que
    -- queda debajo del umbral manda un mensaje en cada corrida del cron.
    activa         boolean       not null default true,
    disparada_en   timestamptz,
    precio_disparo numeric(18,6),

    created_at     timestamptz   not null default now()
);

-- El cron pide "todas las activas": este índice es el que evita que esa
-- consulta escanee la tabla entera a medida que crezca.
create index if not exists alertas_activas_idx
    on public.alertas (activa) where activa;
create index if not exists alertas_user_idx on public.alertas (user_id);

-- ------------------------------------------------------------------ RLS ----
alter table public.alertas enable row level security;

drop policy if exists "alertas: leer las propias" on public.alertas;
drop policy if exists "alertas: borrar las propias" on public.alertas;

-- La web puede leer y borrar las suyas. No hay policy de INSERT ni de UPDATE:
-- las alertas las crea el bot por Telegram, que escribe con service_role y
-- saltea RLS. Lo que no está permitido, está prohibido.
create policy "alertas: leer las propias"
    on public.alertas for select
    to authenticated
    using (auth.uid() = user_id);

create policy "alertas: borrar las propias"
    on public.alertas for delete
    to authenticated
    using (auth.uid() = user_id);

-- Verificación: dos policies, select y delete, para authenticated.
select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'alertas';
