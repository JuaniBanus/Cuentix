-- Termómetro de inflación personal: campos para poder comparar precios.

alter table public.movimientos
    add column if not exists clave_item text,

    add column if not exists comercio text,

    add column if not exists cantidad numeric(14,3),
    add column if not exists unidad text,
    add column if not exists precio_unitario numeric(14,2);

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.movimientos'::regclass
          and conname = 'movimientos_clave_item_check'
    ) then
        alter table public.movimientos
            add constraint movimientos_clave_item_check
            check (clave_item is null or char_length(clave_item) between 1 and 60);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.movimientos'::regclass
          and conname = 'movimientos_cantidad_check'
    ) then
        alter table public.movimientos
            add constraint movimientos_cantidad_check
            check (cantidad is null or cantidad > 0);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.movimientos'::regclass
          and conname = 'movimientos_precio_unitario_check'
    ) then
        alter table public.movimientos
            add constraint movimientos_precio_unitario_check
            check (precio_unitario is null or precio_unitario > 0);
    end if;
end $$;

create index if not exists movimientos_clave_item_idx
    on public.movimientos (clave_item, fecha)
    where clave_item is not null;

update public.movimientos
set clave_item = lower(trim(regexp_replace(descripcion, '\s+', ' ', 'g')))
where clave_item is null
  and descripcion is not null
  and char_length(trim(descripcion)) between 1 and 60;

select
    count(*)                          as filas,
    count(clave_item)                 as con_clave,
    count(distinct clave_item)        as items_distintos
from public.movimientos;
