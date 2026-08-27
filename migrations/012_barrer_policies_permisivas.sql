-- Barrer cualquier policy que deje ver datos ajenos.


select
    p.tablename,
    p.policyname,
    p.cmd,
    p.roles,
    case
        when btrim(coalesce(p.qual, '')) in ('true', '(true)')
          or btrim(coalesce(p.with_check, '')) in ('true', '(true)')
          or (p.cmd in ('SELECT', 'UPDATE', 'DELETE', 'ALL') and p.qual is null)
            then 'PERMISIVA - deja ver o escribir lo de todos'
        when coalesce(p.qual, '') || coalesce(p.with_check, '') like '%uid()%'
            then 'ok - filtra por auth.uid()'
        else 'REVISAR A MANO'
    end as veredicto,
    case when c.column_name is null then 'sin dueño (dato público)' else 'con dueño' end as tipo_tabla,
    p.qual,
    p.with_check
from pg_policies p
left join information_schema.columns c
       on c.table_schema = p.schemaname
      and c.table_name   = p.tablename
      and c.column_name  = 'user_id'
where p.schemaname = 'public'
order by
    case when c.column_name is null then 1 else 0 end,
    p.tablename,
    p.cmd;


do $$
declare
    r record;
    n int := 0;
begin
    for r in
        select p.schemaname, p.tablename, p.policyname, p.cmd, p.qual, p.with_check
        from pg_policies p
        where p.schemaname = 'public'
          and exists (
              select 1
              from information_schema.columns c
              where c.table_schema = p.schemaname
                and c.table_name   = p.tablename
                and c.column_name  = 'user_id'
          )
          and p.permissive = 'PERMISSIVE'
          and (
                 btrim(coalesce(p.qual, ''))       in ('true', '(true)')
              or btrim(coalesce(p.with_check, '')) in ('true', '(true)')
              or (p.cmd in ('SELECT', 'UPDATE', 'DELETE', 'ALL') and p.qual is null)
          )
    loop
        raise notice 'Borro %.% -> "%"  [cmd=%  qual=%  with_check=%]',
            r.schemaname, r.tablename, r.policyname, r.cmd,
            coalesce(r.qual, '(sin using)'), coalesce(r.with_check, '(sin with check)');

        execute format('drop policy %I on %I.%I',
                       r.policyname, r.schemaname, r.tablename);
        n := n + 1;
    end loop;

    if n = 0 then
        raise notice 'No habia ninguna policy permisiva sobre tablas con dueño.';
    else
        raise notice 'Borradas: % policy(s) permisiva(s).', n;
    end if;
end $$;


select
    p.tablename,
    p.cmd,
    p.policyname,
    p.qual,
    p.with_check
from pg_policies p
join information_schema.columns c
  on c.table_schema = p.schemaname
 and c.table_name   = p.tablename
 and c.column_name  = 'user_id'
where p.schemaname = 'public'
order by p.tablename, p.cmd, p.policyname;


select c.table_name as tabla_sin_policy_de_lectura
from information_schema.columns c
where c.table_schema = 'public'
  and c.column_name = 'user_id'
  and not exists (
      select 1 from pg_policies p
      where p.schemaname = 'public'
        and p.tablename = c.table_name
        and p.cmd in ('SELECT', 'ALL')
  );


select 'policy permisiva' as problema,
       p.tablename        as objeto,
       p.policyname       as detalle,
       coalesce(p.qual, p.with_check) as expresion
from pg_policies p
join information_schema.columns c
  on c.table_schema = p.schemaname
 and c.table_name   = p.tablename
 and c.column_name  = 'user_id'
where p.schemaname = 'public'
  and p.permissive = 'PERMISSIVE'
  and (
         btrim(coalesce(p.qual, ''))       in ('true', '(true)')
      or btrim(coalesce(p.with_check, '')) in ('true', '(true)')
      or (p.cmd in ('SELECT', 'UPDATE', 'DELETE', 'ALL') and p.qual is null)
  )

union all

select 'RLS apagado',
       cl.relname,
       'la tabla tiene user_id y relrowsecurity = false',
       null
from pg_class cl
where cl.relnamespace = 'public'::regnamespace
  and cl.relkind = 'r'
  and not cl.relrowsecurity
  and exists (
      select 1 from information_schema.columns c
      where c.table_schema = 'public'
        and c.table_name = cl.relname
        and c.column_name = 'user_id'
  )

union all

select 'vista sin security_invoker',
       cl.relname,
       'lee las tablas de abajo salteando RLS',
       null
from pg_class cl
where cl.relnamespace = 'public'::regnamespace
  and cl.relkind = 'v'
  and coalesce(array_to_string(cl.reloptions, ','), '') not like '%security_invoker=on%';
