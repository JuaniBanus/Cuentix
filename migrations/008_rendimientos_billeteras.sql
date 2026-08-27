-- Comparador de rendimientos de billeteras virtuales.

create table if not exists public.rendimientos_billeteras (
    id                  uuid          primary key default gen_random_uuid(),

    nombre              text          not null unique
                                      check (char_length(nombre) between 1 and 60),

    tipo                text          not null
                                      check (tipo in ('fci', 'cuenta_remunerada')),

    tna                 numeric(7,4)  not null check (tna >= 0 and tna < 1000),

    tope_monto          numeric(14,2) check (tope_monto is null or tope_monto > 0),

    fecha_actualizacion date          not null,

    fondo               text,

    fuente              text          not null default 'argentinadatos',

    sincronizado_en     timestamptz   not null default now()
);

create index if not exists rendimientos_billeteras_tna_idx
    on public.rendimientos_billeteras (tna desc);

alter table public.rendimientos_billeteras enable row level security;

drop policy if exists "rendimientos: leer" on public.rendimientos_billeteras;

create policy "rendimientos: leer"
    on public.rendimientos_billeteras for select
    to authenticated
    using (true);

select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'rendimientos_billeteras';
