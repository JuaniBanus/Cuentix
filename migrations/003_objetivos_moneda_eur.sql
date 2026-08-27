-- Amplía la restricción de `moneda` en `objetivos` para aceptar EUR.


alter table public.objetivos
    drop constraint if exists objetivos_moneda_check;

alter table public.objetivos
    add constraint objetivos_moneda_check
    check (moneda in ('ARS', 'USD', 'EUR'));

select pg_get_constraintdef(oid) as definicion
from pg_constraint
where conrelid = 'public.objetivos'::regclass
  and conname = 'objetivos_moneda_check';
