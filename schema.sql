-- Esquema de la base. Correr una sola vez en Supabase:
--   Dashboard -> SQL Editor -> New query -> pegar esto -> Run
--
-- Es idempotente: se puede volver a correr sin romper nada.

create table if not exists public.movimientos (
    id          bigint generated always as identity primary key,

    -- Fecha del movimiento según el usuario ("ayer", "el 3"), no la de carga.
    fecha       date          not null,

    -- Los cuatro valores de TipoMovimiento (app/models.py).
    tipo        text          not null
                check (tipo in ('gasto', 'ingreso', 'inversion', 'ahorro')),

    -- numeric(14,2) para que coincida con max_digits=14 / decimal_places=2 del
    -- modelo. Siempre positivo: el signo lo aporta `tipo`.
    monto       numeric(14,2) not null check (monto > 0),

    -- Los tres valores de Moneda (app/models.py). Si se agrega uno nuevo,
    -- hay que ampliar este check o el insert falla.
    moneda      text          not null default 'ARS'
                check (moneda in ('ARS', 'USD', 'EUR')),

    -- Se guarda normalizada en minúsculas (ver _aplicar_filtros en app/db.py:94:
    -- el filtro compara con eq, así que un 'Super' guardado nunca matchearía).
    categoria   text          not null check (char_length(categoria) between 1 and 60),

    -- Etiqueta corta generada por el parser ("pancho y coca"), no el mensaje
    -- del usuario: el texto original se usa en memoria y no se persiste.
    -- El check sigue admitiendo hasta 500 por las filas viejas, anteriores al
    -- cambio; las nuevas vienen recortadas a 60 desde app/parser.py.
    descripcion text          not null check (char_length(descripcion) between 1 and 500),

    -- Dónde está la plata: efectivo, banco, billetera virtual, caja de
    -- seguridad. Nullable a propósito y sin default: si el mensaje no dice
    -- dónde, el parser deja null en vez de inventar un lugar. Un '' no puede
    -- entrar, para que "vacío" tenga una sola representación.
    cuenta      text          check (cuenta is null or char_length(cuenta) between 1 and 40),

    created_at  timestamptz   not null default now()
);

-- Los reportes siempre acotan por fecha y casi siempre por tipo.
create index if not exists movimientos_fecha_idx
    on public.movimientos (fecha desc, id desc);

create index if not exists movimientos_tipo_fecha_idx
    on public.movimientos (tipo, fecha desc);

create index if not exists movimientos_categoria_idx
    on public.movimientos (categoria);

-- RLS activo: con la clave anon —la que está a la vista en web/js/config.js—
-- no se puede tocar nada salvo lo que habilite una policy. La clave
-- service_role que usa el bot saltea RLS por diseño.
alter table public.movimientos enable row level security;

-- La web necesita LEER los movimientos, y para eso hace falta esta policy: sin
-- ella el dashboard entra pero muestra todo en cero, porque PostgREST devuelve
-- una lista vacía en vez de un error de permisos.
--
-- Solo SELECT: la web no escribe movimientos, los carga el bot.
--
-- `using (true)` = cualquier usuario logueado ve todos los movimientos. Hoy es
-- correcto porque la base es de un solo dueño: la tabla no tiene user_id. El
-- día que haya un segundo usuario, esto pasa a ser el agujero a tapar, y hay
-- que agregar user_id acá y en el bot.
drop policy if exists "movimientos: leer con sesión" on public.movimientos;

create policy "movimientos: leer con sesión"
    on public.movimientos for select
    to authenticated
    using (true);


-- ---------------------------------------------------------------------------
-- Cambios sobre bases que ya existen
--
-- El `create table if not exists` de arriba no toca una tabla ya creada, así
-- que las columnas nuevas van también acá. Correr este archivo entero de nuevo
-- es seguro: `add column if not exists` no hace nada si la columna ya está, y
-- con ella se saltea su check, así que tampoco se duplica la restricción.
-- ---------------------------------------------------------------------------

alter table public.movimientos
    add column if not exists cuenta text
        check (cuenta is null or char_length(cuenta) between 1 and 40);


-- ---------------------------------------------------------------------------
-- Objetivos de ahorro
--
-- A diferencia de movimientos, esta tabla la escribe la WEB, con la sesión del
-- usuario. Por eso lleva user_id y policies por usuario: ya está lista para
-- multiusuario aunque hoy la use una sola persona.
-- ---------------------------------------------------------------------------

create table if not exists public.objetivos (
    id              uuid          primary key default gen_random_uuid(),

    -- El default lo saca del JWT, así el cliente no puede elegirlo (y si lo
    -- manda, la policy de INSERT lo rechaza igual).
    -- NOT NULL a propósito: una fila con user_id null no sería de nadie y
    -- quedaría invisible para todos, imposible de leer y de borrar.
    user_id         uuid          not null default auth.uid()
                                  references auth.users(id) on delete cascade,

    nombre          text          not null check (char_length(nombre) between 1 and 60),
    descripcion     text          check (descripcion is null or char_length(descripcion) <= 300),

    monto_objetivo  numeric(14,2) not null check (monto_objetivo > 0),
    -- Los mismos tres códigos que `movimientos`: un ahorro en euros se imputa
    -- a un objetivo, y si acá no entrara EUR el objetivo no se podría crear.
    moneda          text          not null default 'ARS'
                                  check (moneda in ('ARS', 'USD', 'EUR')),

    -- Nullable: un objetivo puede no tener fecha ("cambiar el auto, algún día").
    fecha_estimada  date,

    prioridad       text          not null default 'media'
                                  check (prioridad in ('alta', 'media', 'baja')),

    -- El color se guarda como nombre de token ("cat-3"), no como hex: así la
    -- web lo resuelve a var(--cat-3) y se ve bien en tema claro y oscuro.
    icono           text          check (icono is null or char_length(icono) between 1 and 8),
    color           text          check (color is null or char_length(color) between 1 and 20),

    estado          text          not null default 'activo'
                                  check (estado in ('activo', 'completado', 'pausado')),

    created_at      timestamptz   not null default now()
);

-- Toda policy filtra por user_id: sin este índice, cada consulta escanea la
-- tabla entera y recién ahí descarta lo ajeno.
create index if not exists objetivos_user_idx on public.objetivos (user_id);
create index if not exists objetivos_user_estado_idx on public.objetivos (user_id, estado);

alter table public.objetivos enable row level security;

-- CREATE POLICY no admite IF NOT EXISTS: se borra y se vuelve a crear.
drop policy if exists "objetivos: leer los propios"   on public.objetivos;
drop policy if exists "objetivos: crear propios"      on public.objetivos;
drop policy if exists "objetivos: editar los propios" on public.objetivos;
drop policy if exists "objetivos: borrar los propios" on public.objetivos;

-- USING filtra las filas que ya existen; WITH CHECK valida cómo quedan después
-- de escribir. Por eso INSERT solo lleva la segunda y DELETE solo la primera.
create policy "objetivos: leer los propios"
    on public.objetivos for select
    to authenticated
    using ((select auth.uid()) = user_id);

create policy "objetivos: crear propios"
    on public.objetivos for insert
    to authenticated
    with check ((select auth.uid()) = user_id);

-- La única con las dos, y omitir WITH CHECK acá es el error clásico: sin él
-- podrías editar tu objetivo y en el mismo UPDATE cambiarle el user_id a otra
-- persona, regalándoselo o sacándotelo de encima.
create policy "objetivos: editar los propios"
    on public.objetivos for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "objetivos: borrar los propios"
    on public.objetivos for delete
    to authenticated
    using ((select auth.uid()) = user_id);


-- Imputar un ahorro a un objetivo. `on delete set null`: si borrás el
-- objetivo, el ahorro no se borra —esa plata la apartaste igual—, solo deja de
-- estar asignado.
alter table public.movimientos
    add column if not exists objetivo_id uuid
        references public.objetivos(id) on delete set null;

-- Postgres NO indexa las claves foráneas solo. Sin esto, "los movimientos de
-- este objetivo" escanea toda la tabla, y borrar un objetivo también.
create index if not exists movimientos_objetivo_idx
    on public.movimientos (objetivo_id) where objetivo_id is not null;
