-- Amplía la restricción de `moneda` en `objetivos` para aceptar EUR.
--
-- La migración 001 amplió `movimientos`, pero no `objetivos`: esa tabla se
-- creó en otra rama y las dos se juntaron recién al fusionar. El resultado es
-- que un ahorro en euros se guarda bien pero el objetivo al que se imputa no
-- se puede crear, porque `crear_objetivo` recibe un `Moneda` que ya incluye
-- EUR y el check de la tabla todavía lo rechaza.
--
-- El `create table if not exists` de schema.sql no arregla una tabla que ya
-- existe, así que sobre una base ya creada hay que correr esto.
--
-- Correr una vez en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

-- Por si el nombre del constraint no fuera el que asume el script:
--   select conname from pg_constraint
--   where conrelid = 'public.objetivos'::regclass and contype = 'c';

alter table public.objetivos
    drop constraint if exists objetivos_moneda_check;

alter table public.objetivos
    add constraint objetivos_moneda_check
    check (moneda in ('ARS', 'USD', 'EUR'));

-- Verificación: tiene que listar los tres códigos.
select pg_get_constraintdef(oid) as definicion
from pg_constraint
where conrelid = 'public.objetivos'::regclass
  and conname = 'objetivos_moneda_check';
