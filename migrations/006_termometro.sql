-- Termómetro de inflación personal: campos para poder comparar precios.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.
--
-- POR QUÉ HACEN FALTA COLUMNAS NUEVAS
--
-- Un movimiento guarda un TOTAL, y un total es precio × cantidad. Comparar
-- totales mide cuánto gastaste, no cuánto salen las cosas: cuatro cargas de
-- nafta de $40.000, $15.400, $250 y $40.000 no dicen nada sobre el precio del
-- litro, dicen que cargaste distinto cada vez.
--
-- `descripcion` tampoco alcanza para agrupar: es una etiqueta libre y el mismo
-- comercio aparece como "coto", "el coto" o "compra en coto". Agrupar por ese
-- texto fragmentaría el historial justo donde hace falta que sea continuo.

alter table public.movimientos
    -- Identificador ESTABLE del ítem, calculado por el bot al guardar y no
    -- derivado en cada consulta: si se recalculara, el mismo algoritmo
    -- agruparía distinto a medida que crece el historial y el termómetro
    -- cambiaría de números solo.
    add column if not exists clave_item text,

    -- DÓNDE se compró, separado de `categoria` que es QUÉ tipo de gasto es.
    -- Hoy las dos cosas se mezclan en `descripcion`.
    add column if not exists comercio text,

    -- Precio por unidad y su unidad. Es la única forma honesta de medir
    -- inflación en compras variables: sin esto, "el súper subió 30%" puede
    -- ser que compraste más. Nullable porque la mayoría de los mensajes no lo
    -- dicen, y forzarlo llevaría a inventarlo.
    add column if not exists cantidad numeric(14,3),
    add column if not exists unidad text,
    add column if not exists precio_unitario numeric(14,2);

-- Checks aparte del add column: en Postgres no se pueden declarar inline con
-- IF NOT EXISTS, y así el script se puede volver a correr sin error.
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

-- El termómetro pide "todas las compras de este ítem, ordenadas por fecha".
create index if not exists movimientos_clave_item_idx
    on public.movimientos (clave_item, fecha)
    where clave_item is not null;

-- ------------------------------------------------------- Relleno inicial ---
-- Las filas viejas no tienen clave_item. Se completa con la normalización
-- mínima de `descripcion` —minúsculas, sin espacios de más— para que el
-- historial existente no quede afuera del análisis.
--
-- Es la versión pobre de lo que hace app/items.py (que además saca tildes,
-- artículos y agrupa parecidos). Alcanza para no perder lo ya cargado; lo que
-- entre de ahora en más va con la clave buena.
update public.movimientos
set clave_item = lower(trim(regexp_replace(descripcion, '\s+', ' ', 'g')))
where clave_item is null
  and descripcion is not null
  and char_length(trim(descripcion)) between 1 and 60;

-- Verificación: cuántas filas quedaron con clave y cuántos ítems distintos hay.
select
    count(*)                          as filas,
    count(clave_item)                 as con_clave,
    count(distinct clave_item)        as items_distintos
from public.movimientos;
