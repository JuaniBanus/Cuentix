-- =========================================================================
-- Auditoría de RLS. NO MODIFICA NADA: son cuatro consultas de lectura.
-- =========================================================================
--
-- POR QUÉ HACE FALTA UN ARCHIVO PARA ESTO
--
-- Se puede probar RLS desde afuera, con la clave anon del front, pidiendo cada
-- tabla sin sesión. Esa prueba tiene un punto ciego: una tabla VACÍA devuelve
-- cero filas esté protegida o no. En una auditoría real de este proyecto, cinco
-- de diez tablas estaban vacías, así que la mitad del sistema quedó sin
-- verificar y el resultado igual parecía un aprobado general.
--
-- Estas consultas miran el estado declarado en el catálogo de Postgres, que no
-- depende de que haya datos cargados.
--
-- CÓMO SE LEE EL RESULTADO
--
-- Consulta 1: toda tabla de `public` tiene que decir rls_activo = true.
--   Una en false es una fuga abierta: la clave anon está en el JavaScript, así
--   que cualquiera puede leer esa tabla entera.
--
-- Consulta 2: toda tabla con RLS activo tiene que tener AL MENOS una policy.
--   RLS activo sin policies no es un permiso amplio, es lo contrario: niega
--   todo. Se ve igual que "protegida" en la prueba de afuera y rompe la app.
--
-- Consulta 3: el detalle, para leer qué permite cada una.
--
-- Consulta 4: las peligrosas. Una policy `using (true)` para SELECT es
--   correcta en datos compartidos —`rendimientos_billeteras` son las tasas
--   públicas, iguales para todos— y es una fuga en cualquier tabla que tenga
--   una columna user_id. Esta consulta separa un caso del otro.


-- --------------------------------------------------------------- 1 de 4 ---
-- RLS activo, tabla por tabla.
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


-- --------------------------------------------------------------- 2 de 4 ---
-- Tablas con RLS pero sin ninguna policy: niegan todo, incluso a su dueño.
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


-- --------------------------------------------------------------- 3 de 4 ---
-- El detalle de cada policy.
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


-- --------------------------------------------------------------- 4 de 4 ---
-- Policies abiertas: `using (true)` sobre una tabla que tiene dueño por fila.
--
-- Es la forma más común de filtrar datos entre cuentas, y no se nota probando
-- con un solo usuario: con una sola cuenta cargada, "ver todo" y "ver lo mío"
-- devuelven exactamente lo mismo.
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
