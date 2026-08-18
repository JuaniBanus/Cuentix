-- El superusuario administra cuentas y no ve finanzas de nadie.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.
--
-- =========================================================================
-- ANTES: CORRER LA 013
-- =========================================================================
--
-- La 013 le devuelve a juanbanuss los movimientos que la 009 le había asignado
-- al admin. Si estas policies se aplican primero, esos movimientos —que
-- todavía serían del admin— quedan invisibles desde el navegador para todos.
-- No se pierden, pero solo se ven desde el SQL Editor, y el diagnóstico se
-- vuelve confuso justo cuando menos conviene.
--
-- =========================================================================
-- POR QUÉ RESTRICTIVE Y NO OTRA COSA
-- =========================================================================
--
-- Es el mecanismo inverso al bug que apareció con la policy vieja de
-- `movimientos` (ver migrations/012):
--
--   PERMISSIVE  -> se suman con OR.  Una sola `using (true)` vuelve inútiles a
--                  todas las demás.
--   RESTRICTIVE -> se cruzan con AND. No hay forma de anularlas agregando otra
--                  policy: lo que niegan queda negado.
--
-- Por eso el "no mira finanzas" va como restrictiva y no como una condición más
-- adentro de las que ya están. Si mañana alguien vuelve a dejar suelto un
-- `using (true)`, el agujero afectaría a los usuarios comunes pero el
-- superusuario seguiría sin ver una sola fila.
--
-- Y no otorga nada: una restrictiva solo puede quitar. El acceso lo siguen
-- dando las permisivas de la 009; esta les pone un techo.
--
-- =========================================================================
-- LO QUE NO HACE FALTA TOCAR
-- =========================================================================
--
-- * `perfiles` ya está bien desde la 009: revoke all + grant select + grant
--   update de UNA columna. Un usuario común no puede cambiar `estado` ni `rol`
--   ni editando el request, porque lo frena el permiso de COLUMNA, que se
--   evalúa antes que RLS.
--
-- * `admin_cambiar_estado(uuid, text)` (009) ya es el único camino para activar
--   y pausar, ya exige superusuario y ya impide que se pause a sí mismo. El
--   panel de la web la llama y no hay nada nuevo que escribir.
--
-- * El bot usa service_role y saltea RLS: nada de esto lo afecta. El
--   aislamiento del bot es app/usuarios.py + el filtro por user_id.


-- =========================================================================
-- PASO 1 - el superusuario no toca ninguna tabla con dueño
-- =========================================================================
--
-- Las siete. No solo las tres de las pantallas: si quedara una afuera, el
-- superusuario podría leer por ahí los retos, los recordatorios o los resúmenes
-- mensuales de otro, que también son suyos y también son privados.
--
-- `for all` cubre las cuatro operaciones. En SELECT y DELETE manda el USING; en
-- INSERT, el WITH CHECK; en UPDATE, los dos. Van iguales a propósito: la
-- respuesta es la misma en cualquier dirección.

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


-- =========================================================================
-- PASO 2 - debe_cambiar_password pasa a default false
-- =========================================================================
--
-- La 009 lo dejó en `true` pensando en un alta con contraseña provisoria. El
-- alta ahora es por INVITACIÓN: la persona elige su propia contraseña en el
-- link del mail. Con el default en true la obligaríamos a cambiar, al primer
-- login, una contraseña que acaba de elegir ella misma.
--
-- Se invierte: el flag se prende A MANO, y solo cuando le entregaste una
-- contraseña que escribiste vos.

alter table public.perfiles alter column debe_cambiar_password set default false;

-- Para pedirle el cambio a alguien puntual (o después de un reseteo):
/*
update public.perfiles set debe_cambiar_password = true
where lower(email) = lower('persona@ejemplo.com');
*/

-- No se agrega ninguna función de administración para esto, igual que con
-- `rol`: es una operación rara, y cada RPC nueva es superficie nueva.


-- =========================================================================
-- PASO 3 - verificación
-- =========================================================================

-- (1) Las siete restrictivas tienen que estar. `permissive` dice RESTRICTIVE.
select tablename, policyname, permissive, cmd, qual
from pg_policies
where schemaname = 'public'
  and permissive = 'RESTRICTIVE'
order by tablename;

-- (2) Y ninguna tabla con dueño puede haber quedado sin la suya. Vacío.
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


-- ------------------------------------------------- SIMULACRO, LAS DOS CUENTAS
--
-- Que las policies existan y que funcionen son dos cosas distintas. Esto se
-- hace pasar por cada usuario y cuenta lo que ve. Todo adentro de
-- begin/rollback: no escribe nada.
--
-- Los uuid salen de:  select id, email from auth.users;

-- EL SUPERUSUARIO: las tres tienen que dar 0.
/*
begin;
    set local role authenticated;
    set local request.jwt.claims = '{"sub":"<UUID-DE-AREALEGALES>","role":"authenticated"}';

    select count(*) as movimientos from public.movimientos;
    select count(*) as objetivos   from public.objetivos;
    select count(*) as inversiones from public.inversiones;

    -- Pero SÍ tiene que ver la lista de perfiles: es su trabajo.
    select count(*) as perfiles_que_ve from public.perfiles;
rollback;
*/

-- EL USUARIO COMÚN: movimientos tiene que dar 31, y perfiles 1 (el suyo).
/*
begin;
    set local role authenticated;
    set local request.jwt.claims = '{"sub":"<UUID-DE-JUANBANUSS>","role":"authenticated"}';

    select count(*) as movimientos     from public.movimientos;
    select count(*) as perfiles_que_ve from public.perfiles;
rollback;
*/


-- =========================================================================
-- SI ALGÚN DÍA EL SUPERUSUARIO NECESITA SUS PROPIAS FINANZAS
-- =========================================================================
--
-- No se resuelve aflojando esto. Se resuelve con dos cuentas: una que
-- administra y otra que registra gastos, con mails distintos. Es exactamente el
-- caso que dio origen a todo esto —arealegales administrando y juanbanuss
-- gastando— y la separación es la respuesta, no el problema.
--
-- Bajar la restrictiva para "ver una cosita" deja al que administra pudiendo
-- leer las finanzas de todos, que es lo que este archivo viene a impedir.
