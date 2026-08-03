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

    moneda      text          not null default 'ARS'
                check (moneda in ('ARS', 'USD')),

    -- Se guarda normalizada en minúsculas (ver _aplicar_filtros en app/db.py:94:
    -- el filtro compara con eq, así que un 'Super' guardado nunca matchearía).
    categoria   text          not null check (char_length(categoria) between 1 and 60),

    -- El texto original del mensaje del usuario.
    descripcion text          not null check (char_length(descripcion) between 1 and 500),

    created_at  timestamptz   not null default now()
);

-- Los reportes siempre acotan por fecha y casi siempre por tipo.
create index if not exists movimientos_fecha_idx
    on public.movimientos (fecha desc, id desc);

create index if not exists movimientos_tipo_fecha_idx
    on public.movimientos (tipo, fecha desc);

create index if not exists movimientos_categoria_idx
    on public.movimientos (categoria);

-- RLS activo y SIN policies: nadie puede tocar la tabla con la clave anon
-- (la que se expone en un cliente). La clave service_role que usa el backend
-- saltea RLS por diseño, así que la app sigue funcionando.
alter table public.movimientos enable row level security;
