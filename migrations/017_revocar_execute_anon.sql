-- Cierra los warnings del linter sobre funciones SECURITY DEFINER expuestas.
--
-- Supabase concede EXECUTE a anon y authenticated por default privileges, de
-- forma EXPLICITA. Por eso el `revoke ... from public` de la 009 no las saco:
-- revocar a public no toca un grant explicito. Hay que nombrar al rol.
--
-- CUIDADO CON QUE SE REVOCA A QUIEN:
--
-- es_activo() y es_superusuario() las llaman las policies de RLS, que se
-- evaluan con los permisos de quien consulta. Quitarles EXECUTE a
-- `authenticated` romperia todas las policies de perfiles y las demas que las
-- usan. A `anon` si se le puede: las 28 policies del esquema apuntan a
-- `authenticated`, ninguna a `anon` ni a `public`.
--
-- Las dos funciones de trigger no las llama nadie por RPC: Postgres verifica el
-- permiso sobre la funcion al CREAR el trigger, no cada vez que se dispara, asi
-- que revocarlas no afecta a los triggers que ya existen.

revoke execute on function public.es_activo()       from anon;
revoke execute on function public.es_superusuario() from anon;

revoke execute on function public.perfil_para_usuario_nuevo() from anon, authenticated;
revoke execute on function public.validar_objetivo_propio()   from anon, authenticated;


-- Comprobacion: no deberia quedar ninguna fila.
select
    p.proname                                  as funcion,
    r.rolname                                  as rol,
    'todavia puede ejecutarla'                 as estado
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
cross join (select rolname from pg_roles where rolname in ('anon', 'authenticated')) r
where n.nspname = 'public'
  and p.prosecdef
  and p.proname in ('perfil_para_usuario_nuevo', 'validar_objetivo_propio')
  and has_function_privilege(r.rolname, p.oid, 'EXECUTE')
union all
select p.proname, 'anon', 'todavia puede ejecutarla'
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in ('es_activo', 'es_superusuario')
  and has_function_privilege('anon', p.oid, 'EXECUTE');


-- Vuelta atras, si algo se rompiera:
--   grant execute on function public.es_activo()       to anon;
--   grant execute on function public.es_superusuario() to anon;
--   grant execute on function public.perfil_para_usuario_nuevo() to anon, authenticated;
--   grant execute on function public.validar_objetivo_propio()   to anon, authenticated;
