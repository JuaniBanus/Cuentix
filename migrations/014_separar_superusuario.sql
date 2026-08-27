-- El superusuario administra cuentas y no ve finanzas de nadie.


do $$
declare
    t text;
begin
    foreach t in array array[
        'movimientos', 'objetivos', 'inversiones',
        'alertas', 'recordatorios', 'retos', 'narrativas'
    ] loop
        execute format(
            'drop policy if exists %I on public.%I',
            'sin finanzas para el superusuario', t
        );

        execute format($f$
            create policy %I on public.%I
                as restrictive
                for all
                to authenticated
                using      (not (select public.es_superusuario()))
                with check (not (select public.es_superusuario()))
        $f$, 'sin finanzas para el superusuario', t);

        raise notice 'Policy restrictiva puesta en public.%', t;
    end loop;
end $$;


alter table public.perfiles alter column debe_cambiar_password set default false;


select tablename, policyname, permissive, cmd, qual
from pg_policies
where schemaname = 'public'
  and permissive = 'RESTRICTIVE'
order by tablename;

select c.table_name as tabla_sin_restrictiva
from information_schema.columns c
where c.table_schema = 'public'
  and c.column_name = 'user_id'
  and c.table_name in ('movimientos', 'objetivos', 'inversiones',
                       'alertas', 'recordatorios', 'retos', 'narrativas')
  and not exists (
      select 1 from pg_policies p
      where p.schemaname = 'public'
        and p.tablename = c.table_name
        and p.permissive = 'RESTRICTIVE'
  );


