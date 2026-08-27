-- Auditoría de RLS. NO MODIFICA NADA: son cuatro consultas de lectura.


select
    c.relname                                    as tabla,
    c.relrowsecurity                             as rls_activo,
    c.relforcerowsecurity                        as forzado_al_dueno,
    case when c.relrowsecurity then 'ok'
         else 'PELIGRO: sin RLS, la clave anon lee todo' end as veredicto
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
order by c.relrowsecurity, c.relname;


select
    c.relname as tabla,
    'RLS activo y CERO policies: nadie puede leer, ni siquiera el dueño'
        as advertencia
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
  and c.relrowsecurity
  and not exists (
      select 1 from pg_policies p
      where p.schemaname = 'public' and p.tablename = c.relname
  )
order by c.relname;


select
    tablename  as tabla,
    policyname as policy,
    cmd        as operacion,
    roles,
    coalesce(qual, '(sin condición de lectura)')      as condicion_using,
    coalesce(with_check, '(sin condición de escritura)') as condicion_check
from pg_policies
where schemaname = 'public'
order by tablename, cmd, policyname;


select
    p.tablename  as tabla,
    p.policyname as policy,
    p.cmd        as operacion,
    p.roles,
    case
        when exists (
            select 1 from information_schema.columns col
            where col.table_schema = 'public'
              and col.table_name = p.tablename
              and col.column_name = 'user_id'
        )
        then 'REVISAR: la tabla tiene user_id y esta policy no filtra por dueño'
        else 'ok: dato compartido, sin dueño por fila'
    end as veredicto
from pg_policies p
where p.schemaname = 'public'
  and (p.qual = 'true' or p.with_check = 'true')
order by p.tablename, p.policyname;
