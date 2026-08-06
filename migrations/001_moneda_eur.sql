-- Amplía la restricción de `moneda` para aceptar EUR además de ARS y USD.
--
-- Necesario porque app/models.py incorporó Moneda.EUR: sin esto, un
-- movimiento en euros pasa la validación de Pydantic y falla recién en el
-- INSERT, con violación de check.
--
-- Correr una vez en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

-- Por si el nombre del constraint no fuera el que asume el script:
--   select conname from pg_constraint
--   where conrelid = 'public.movimientos'::regclass and contype = 'c';

alter table public.movimientos
    drop constraint if exists movimientos_moneda_check;

alter table public.movimientos
    add constraint movimientos_moneda_check
    check (moneda in ('ARS', 'USD', 'EUR'));

-- Verificación: tiene que listar los tres códigos.
select pg_get_constraintdef(oid) as definicion
from pg_constraint
where conrelid = 'public.movimientos'::regclass
  and conname = 'movimientos_moneda_check';
