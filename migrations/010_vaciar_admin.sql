-- #########################################################################
-- ##  NO CORRAS ESTE ARCHIVO. QUEDO OBSOLETO.                            ##
-- ##                                                                     ##
-- ##  Este script BORRA los datos del administrador. Se escribio cuando   ##
-- ##  parecian de prueba, y no lo eran: son 31 movimientos reales de la   ##
-- ##  cuenta personal (juanbanuss@gmail.com) que la 009 le asigno al      ##
-- ##  admin.                                                             ##
-- ##                                                                     ##
-- ##  Lo que hay que correr es migrations/013_reasignar_datos_al_dueno.sql ##
-- ##  que los CAMBIA DE DUENO en vez de borrarlos.                        ##
-- ##                                                                     ##
-- ##  Se conserva solo como registro de lo que se penso en su momento.    ##
-- #########################################################################


-- Dejar la cuenta de administración sin datos financieros.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
--
-- =========================================================================
-- QUÉ PASÓ Y POR QUÉ HACE FALTA ESTO
-- =========================================================================
--
-- El PASO 2 de la 009 le asignó a un solo usuario TODOS los movimientos que ya
-- existían, porque antes de esa migración las filas no tenían dueño y había que
-- darles uno. Ese usuario terminó siendo el de administración, así que hoy
-- `arealegales` entra a la web y ve cuentas, saldos y categorías que no le
-- corresponden.
--
-- Acá se borran. La decisión es que ese historial era de prueba.
--
-- ESTO BORRA DATOS Y NO SE DESHACE. Por eso el archivo va en tres tiempos:
--
--   PASO A - contar, sin tocar nada. Se mira el resultado ANTES de seguir.
--   PASO B - respaldar en una tabla, por si el conteo sorprende.
--   PASO C - borrar.
--
-- Están separados a propósito: el PASO A se corre solo, se lee, y recién ahí se
-- corren los otros dos. Correr el archivo entero de una también funciona, pero
-- se pierde la oportunidad de frenar.
--
-- ------------------------------------------------------------------------
-- Y LO MÁS IMPORTANTE, QUE NO ES EL BORRADO
--
-- Si el chat de Telegram del administrador sigue vinculado a su cuenta, la
-- próxima vez que le escriba al bot vuelve a cargar datos ahí y estamos en el
-- mismo lugar. El PASO C también desvincula ese chat: una cuenta que solo
-- administra no tiene por qué tener un chat asociado.
--
-- Si querés seguir cargando gastos desde Telegram, vinculá ese chat_id a tu
-- cuenta de usuario (la personal), no a la de administración. Está explicado en
-- la sección "VINCULAR UN CHAT" de migrations/009_multiusuario.sql.
-- =========================================================================


-- =========================================================================
-- PASO A - contar, sin borrar nada
-- =========================================================================
--
-- Correr SOLO esto primero y mirar los números. Si alguno es más grande de lo
-- que esperabas, frená acá: eso no es historial de prueba.

select
    t.tabla,
    t.filas
from (
    select 'movimientos'  as tabla, count(*) as filas from public.movimientos  where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'objetivos',    count(*) from public.objetivos    where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'inversiones',  count(*) from public.inversiones  where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'alertas',      count(*) from public.alertas      where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'recordatorios',count(*) from public.recordatorios where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'retos',        count(*) from public.retos        where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'narrativas',   count(*) from public.narrativas   where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
    union all
    select 'fotos (storage)', count(*) from storage.objects
        where bucket_id = 'objetivos'
          and (storage.foldername(name))[1] = (select id::text from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
) t
order by t.filas desc;

-- Y el detalle de los movimientos, para reconocerlos de un vistazo. Si acá
-- aparecen gastos reales tuyos de meses pasados, NO sigas: cambiá de plan y
-- movelos a tu cuenta personal en vez de borrarlos.
select fecha, tipo, monto, moneda, categoria, descripcion
from public.movimientos
where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
order by fecha desc
limit 30;


-- =========================================================================
-- PASO B - respaldo
-- =========================================================================
--
-- Una sola tabla con todo adentro como jsonb, en vez de siete copias. No es
-- para consultarla: es para poder mirar qué había si el borrado sorprende.
--
-- Cuando ya no la necesites:  drop table public.respaldo_010;

create table if not exists public.respaldo_010 (
    id          bigint generated always as identity primary key,
    tabla       text        not null,
    fila        jsonb       not null,
    guardado_en timestamptz not null default now()
);

-- Sin esto, la tabla de respaldo sería el agujero más grande de la base: en
-- Supabase, una tabla nueva de `public` nace con permisos para `anon` y
-- `authenticated`, así que quedaría legible desde el navegador con la anon key
-- —y adentro está justamente todo lo que las policies de la 009 protegen—.
--
-- RLS activo y CERO policies: lo único que puede leerla es service_role o el
-- SQL Editor. Lo que no está permitido, está prohibido.
alter table public.respaldo_010 enable row level security;
revoke all on public.respaldo_010 from anon, authenticated;

do $$
declare
    mi_email text := 'arealegalesastarsa@gmail.com';   -- <<< la cuenta de administración
    mi_id    uuid;
    n        bigint;
begin
    select id into mi_id from auth.users where lower(email) = lower(mi_email);
    if mi_id is null then
        raise exception 'No existe ningún usuario con el email %.', mi_email;
    end if;

    -- Si el respaldo ya se corrió antes, no se duplica.
    delete from public.respaldo_010;

    insert into public.respaldo_010 (tabla, fila)
    select 'movimientos', to_jsonb(m) from public.movimientos m where m.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'objetivos', to_jsonb(o) from public.objetivos o where o.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'inversiones', to_jsonb(i) from public.inversiones i where i.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'alertas', to_jsonb(a) from public.alertas a where a.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'recordatorios', to_jsonb(r) from public.recordatorios r where r.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'retos', to_jsonb(r) from public.retos r where r.user_id = mi_id;
    insert into public.respaldo_010 (tabla, fila)
    select 'narrativas', to_jsonb(n2) from public.narrativas n2 where n2.user_id = mi_id;

    select count(*) into n from public.respaldo_010;
    raise notice 'Respaldadas % filas en public.respaldo_010.', n;
end $$;


-- =========================================================================
-- PASO C - borrar
-- =========================================================================
--
-- Los movimientos van PRIMERO. `movimientos.objetivo_id` referencia a
-- `objetivos` con `on delete set null`, así que al revés Postgres tendría que
-- reescribir cada movimiento imputado para dejarle el objetivo en null, justo
-- antes de borrarlo. Mismo resultado, trabajo de más.

do $$
declare
    mi_email text := 'arealegalesastarsa@gmail.com';   -- <<< la misma de arriba
    mi_id    uuid;
    n_mov bigint; n_obj bigint; n_inv bigint; n_ale bigint;
    n_rec bigint; n_ret bigint; n_nar bigint; n_fot bigint; n_tel bigint;
begin
    select id into mi_id from auth.users where lower(email) = lower(mi_email);
    if mi_id is null then
        raise exception 'No existe ningún usuario con el email %.', mi_email;
    end if;

    delete from public.movimientos   where user_id = mi_id;  get diagnostics n_mov = row_count;
    delete from public.objetivos     where user_id = mi_id;  get diagnostics n_obj = row_count;
    delete from public.inversiones   where user_id = mi_id;  get diagnostics n_inv = row_count;
    delete from public.alertas       where user_id = mi_id;  get diagnostics n_ale = row_count;
    delete from public.recordatorios where user_id = mi_id;  get diagnostics n_rec = row_count;
    delete from public.retos         where user_id = mi_id;  get diagnostics n_ret = row_count;
    delete from public.narrativas    where user_id = mi_id;  get diagnostics n_nar = row_count;

    -- Las fotos de los objetivos. Cada usuario vive en una carpeta con su uuid
    -- (ver migrations/007), así que se borra la carpeta entera.
    --
    -- OJO: esto borra la FILA de storage.objects, que es lo que hace que el
    -- archivo deje de existir para la API. El binario puede quedar un rato en
    -- el almacenamiento hasta que Supabase lo recoja. Si querés asegurarte,
    -- mirá el bucket `objetivos` en Storage y borrá la carpeta a mano.
    delete from storage.objects
    where bucket_id = 'objetivos'
      and (storage.foldername(name))[1] = mi_id::text;
    get diagnostics n_fot = row_count;

    -- Lo que evita que todo esto vuelva a pasar. Ver la nota del encabezado:
    -- con el chat vinculado, el próximo "gasté 5 lucas" recrea el problema.
    delete from public.usuarios_telegram where user_id = mi_id;
    get diagnostics n_tel = row_count;

    raise notice
        'Borrado de %: % movimientos, % objetivos, % inversiones, % alertas, '
        '% recordatorios, % retos, % narrativas, % fotos, % vínculo(s) de Telegram.',
        mi_email, n_mov, n_obj, n_inv, n_ale, n_rec, n_ret, n_nar, n_fot, n_tel;
end $$;


-- =========================================================================
-- Verificación
-- =========================================================================

-- (1) La cuenta de administración tiene que quedar en cero en todo.
select 'movimientos'   as tabla, count(*) as le_queda from public.movimientos   where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'objetivos',    count(*) from public.objetivos    where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'inversiones',  count(*) from public.inversiones  where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'telegram',     count(*) from public.usuarios_telegram where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'));

-- (2) Pero el PERFIL sigue, activo y superusuario: se borraron sus datos, no
-- su cuenta. Si esto no devuelve una fila, algo salió mal.
select email, estado, rol, debe_cambiar_password
from public.perfiles
where lower(email) = lower('arealegalesastarsa@gmail.com');

-- (3) Cómo quedó todo el sistema: quién existe, en qué estado y con qué chat.
select p.email, p.estado, p.rol, t.chat_id, t.alias
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;
