-- Barrer cualquier policy que deje ver datos ajenos.
--
-- Correr en: Supabase -> SQL Editor.
--
-- ESTE ARCHIVO SE CORRE POR PARTES. Mirás el PASO 1, decidís, y recién ahí
-- corrés el PASO 2. Es un borrado: vale la pena ver qué se va antes.
--
-- =========================================================================
-- LAS POLICIES SE SUMAN CON *OR*
-- =========================================================================
--
-- Es la parte que hace que este bug sea tan silencioso. Dos policies PERMISIVAS
-- sobre la misma tabla y la misma operación no se restringen entre sí: se
-- combinan con OR. O sea que
--
--     "leer los propios"    using (auth.uid() = user_id)
--     "lectura movimientos" using (true)
--
-- juntas significan `(auth.uid() = user_id) OR true`, que es `true`. La policy
-- buena sigue ahí, sigue siendo correcta, y no sirve para nada. No hay ningún
-- error ni ningún warning: la app anda igual, solo que cada usuario ve todo.
--
-- Por eso "agregué las policies nuevas" nunca alcanza. Hay que sacar las viejas.
--
-- ------------------------------------------------------------------------
-- POR QUÉ NO ALCANZÓ LA 009
--
-- La 009 las borraba POR NOMBRE, con el nombre que estaba escrito en
-- schema.sql. Si en la base real la policy se llamaba de otra forma —porque se
-- creó a mano, o con una versión anterior del archivo— el `drop policy if
-- exists` no encontró nada y siguió sin decir una palabra. Ese `if exists`, que
-- está para que el script se pueda repetir, también se come el caso en que la
-- policy existe con otro nombre.
--
-- Acá no se nombra ninguna policy. Se buscan por lo que HACEN.
--
-- ------------------------------------------------------------------------
-- LA REGLA
--
-- Una tabla que tiene columna `user_id` guarda datos de alguien. Sobre esa
-- tabla, una policy que no mire el user_id está mal, se llame como se llame.
--
-- Y al revés: `rendimientos_billeteras` NO tiene user_id, y su policy es
-- `using (true)` a propósito. Son TNA públicas, iguales para todos, sin dueño.
-- Esa hay que dejarla: borrarla rompe el comparador de billeteras y no protege
-- absolutamente nada. El PASO 2 no la toca justamente porque la tabla no tiene
-- user_id, y el PASO 1 la muestra aparte para que se vea que quedó afuera a
-- propósito y no por olvido.


-- =========================================================================
-- PASO 1 - qué hay hoy, y el veredicto de cada una
-- =========================================================================
--
-- Correr esto SOLO, y leerlo. Todo lo que diga PERMISIVA es un agujero abierto
-- en este momento.

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
    case when c.column_name is null then 1 else 0 end,   -- primero las que tienen dueño
    p.tablename,
    p.cmd;

-- CÓMO LEER EL RESULTADO
--
-- 'PERMISIVA' sobre una tabla "con dueño"  -> se va en el PASO 2.
--
-- 'PERMISIVA' sobre `rendimientos_billeteras` ("sin dueño") -> se queda. Es
--     correcta: dato público, no hay nada que aislar.
--
-- 'REVISAR A MANO' -> la policy no menciona auth.uid() en su texto pero tampoco
--     es `true`. En esta base es el caso de "perfiles: el super ve todos", que
--     llama a public.es_superusuario(); esa función sí mira auth.uid() adentro,
--     solo que no se ve desde acá. Está bien y se queda. Cualquier OTRA que
--     caiga en esta categoría hay que leerla entera antes de decidir.


-- =========================================================================
-- PASO 2 - borrarlas
-- =========================================================================
--
-- Recorre las policies de todas las tablas de `public` que tengan columna
-- user_id y borra las que dejan pasar todo. No hay ninguna lista de nombres ni
-- de tablas escrita a mano: si mañana aparece una tabla nueva con dueño, este
-- mismo bloque la cubre sin tocarlo.
--
-- Cada borrado sale por `raise notice` con el nombre y el qual que tenía, así
-- queda constancia de qué se fue. Miralos en la pestaña de mensajes del editor.

do $$
declare
    r record;
    n int := 0;
begin
    for r in
        select p.schemaname, p.tablename, p.policyname, p.cmd, p.qual, p.with_check
        from pg_policies p
        where p.schemaname = 'public'
          -- Solo tablas con dueño. Esto es lo que deja afuera a
          -- rendimientos_billeteras sin tener que nombrarla.
          and exists (
              select 1
              from information_schema.columns c
              where c.table_schema = p.schemaname
                and c.table_name   = p.tablename
                and c.column_name  = 'user_id'
          )
          -- Las RESTRICTIVE se combinan con AND, no con OR: esas restan
          -- permisos y nunca son el problema. Solo molestan las permisivas.
          and p.permissive = 'PERMISSIVE'
          and (
                 btrim(coalesce(p.qual, ''))       in ('true', '(true)')
              or btrim(coalesce(p.with_check, '')) in ('true', '(true)')
              -- Sin USING, una operación que lee filas existentes equivale a
              -- true. En INSERT no aplica: ahí nunca hay USING.
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


-- =========================================================================
-- PASO 3 - qué quedó en cada tabla
-- =========================================================================
--
-- Después del barrido, cada tabla con dueño tiene que tener SOLO policies que
-- filtren por auth.uid(). Esta las lista tabla por tabla para poder mirarlas.

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


-- Y el control de que no haya quedado una tabla MUDA.
--
-- Borrar la permisiva sin que exista la buena deja la tabla sin ninguna forma
-- de leerse: la app no da error, muestra todo en cero. Es el efecto secundario
-- más fácil de confundir con "se arregló".
--
-- Si alguna tabla aparece acá, le falta la policy de SELECT: volvé a correr el
-- PASO 4 de migrations/009_multiusuario.sql, que es donde se crean.
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


-- =========================================================================
-- PASO 4 - la consulta de control
-- =========================================================================
--
-- Esta es la que hay que poder correr cualquier día y que dé VACÍO. Guardala:
-- es el chequeo que faltaba, y el que hubiera encontrado este bug solo.
--
-- Cubre las tres formas de dejar datos ajenos a la vista, que no son la misma:
--
--   (a) una policy permisiva sobre una tabla con dueño;
--   (b) una tabla con dueño y RLS directamente apagado;
--   (c) una vista que lee esas tablas sin security_invoker, que corre con los
--       permisos de quien la creó y saltea las policies de abajo.

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

-- (b) Peor que una policy floja: sin RLS no se evalúa ninguna policy, estén
-- como estén.
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

-- (c) Una vista es de quien la crea y, por defecto, lee las tablas de abajo con
-- SUS permisos y no con los de quien consulta: eso saltea RLS por completo. Hoy
-- no hay ninguna vista en public; esto queda para el día que alguien agregue
-- una "para simplificar una consulta".
select 'vista sin security_invoker',
       cl.relname,
       'lee las tablas de abajo salteando RLS',
       null
from pg_class cl
where cl.relnamespace = 'public'::regnamespace
  and cl.relkind = 'v'
  and coalesce(array_to_string(cl.reloptions, ','), '') not like '%security_invoker=on%';
