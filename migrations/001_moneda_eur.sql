-- Amplía la restricción de `moneda` para aceptar EUR además de ARS y USD.


alter table public.movimientos
    drop constraint if exists movimientos_moneda_check;

alter table public.movimientos
    add constraint movimientos_moneda_check
    check (moneda in ('ARS', 'USD', 'EUR'));

select pg_get_constraintdef(oid) as definicion
from pg_constraint
where conrelid = 'public.movimientos'::regclass
  and conname = 'movimientos_moneda_check';
