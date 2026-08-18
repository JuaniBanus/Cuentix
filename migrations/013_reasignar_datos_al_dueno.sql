-- Devolverle al usuario real los datos que la 009 le asignó al administrador.
--
-- Correr en: Supabase -> SQL Editor.
--
-- =========================================================================
-- ESTE ARCHIVO REEMPLAZA A LA 010. NO CORRAS LA 010.
-- =========================================================================
--
-- La 010 BORRA los datos del administrador. Se escribió cuando parecían de
-- prueba. No lo eran: son movimientos reales de la cuenta personal, que la 009
-- le asignó al admin porque antes de esa migración las filas no tenían dueño y
-- había que darles uno.
--
-- Acá no se borra nada. Se cambia de dueño.
--
-- ------------------------------------------------------------------------
-- EL ORDEN NO ES OPCIONAL
--
-- `movimientos` tiene un trigger, `movimientos_objetivo_propio`, que valida en
-- cada UPDATE de user_id que el objetivo apuntado sea del mismo dueño. Si se
-- mueven los movimientos ANTES que los objetivos, el trigger rechaza cada
-- movimiento imputado con "El objetivo X no pertenece al usuario Y".
--
-- Por eso los objetivos van primero. No es una preferencia de estilo: al revés
-- no funciona.
--
-- ------------------------------------------------------------------------
-- SE CORRE POR PARTES
--
--   PASO A - inventario. Se mira y se compara con lo que esperabas (31).
--   PASO B - respaldo.
--   PASO C - reasignar.
--   PASO D - verificar.
--
-- El PASO C es un solo DO: o entra todo o no entra nada. Si algo falla en el
-- medio, Postgres deshace el bloque entero y no quedan datos a medio mover.


-- =========================================================================
-- PASO A - qué hay, y de quién es hoy
-- =========================================================================
--
-- Correr esto SOLO. La columna `del_admin` de movimientos tiene que decir 31.
-- Si dice otra cosa, frená y averiguá por qué antes de mover nada.

with q as (
    select
        (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com')) as admin,
        (select id from auth.users where lower(email) = lower('juanbanuss@gmail.com'))         as duenio
)
select 'movimientos'   as tabla,
       (select count(*) from public.movimientos   where user_id = q.admin)  as del_admin,
       (select count(*) from public.movimientos   where user_id = q.duenio) as ya_del_duenio from q
union all
select 'objetivos',
       (select count(*) from public.objetivos     where user_id = q.admin),
       (select count(*) from public.objetivos     where user_id = q.duenio) from q
union all
select 'inversiones',
       (select count(*) from public.inversiones   where user_id = q.admin),
       (select count(*) from public.inversiones   where user_id = q.duenio) from q
union all
select 'alertas',
       (select count(*) from public.alertas       where user_id = q.admin),
       (select count(*) from public.alertas       where user_id = q.duenio) from q
union all
select 'recordatorios',
       (select count(*) from public.recordatorios where user_id = q.admin),
       (select count(*) from public.recordatorios where user_id = q.duenio) from q
union all
select 'retos',
       (select count(*) from public.retos         where user_id = q.admin),
       (select count(*) from public.retos         where user_id = q.duenio) from q
union all
select 'narrativas',
       (select count(*) from public.narrativas    where user_id = q.admin),
       (select count(*) from public.narrativas    where user_id = q.duenio) from q
union all
select 'telegram (vínculos)',
       (select count(*) from public.usuarios_telegram where user_id = q.admin),
       (select count(*) from public.usuarios_telegram where user_id = q.duenio) from q
union all
select 'fotos en Storage',
       (select count(*) from storage.objects where bucket_id = 'objetivos'
          and (storage.foldername(name))[1] = q.admin::text),
       (select count(*) from storage.objects where bucket_id = 'objetivos'
          and (storage.foldername(name))[1] = q.duenio::text) from q;


-- Los 31, para reconocerlos antes de tocarlos.
select fecha, tipo, monto, moneda, categoria, descripcion
from public.movimientos
where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
order by fecha desc;


-- El único choque posible de todo el traspaso: `narrativas` tiene un índice
-- único (user_id, mes). Si los dos usuarios tienen un resumen del MISMO mes, el
-- update no puede pasar. Esto tiene que dar vacío; si no, el PASO C se aborta
-- solo con un mensaje que lo explica.
with q as (
    select
        (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com')) as admin,
        (select id from auth.users where lower(email) = lower('juanbanuss@gmail.com'))         as duenio
)
select n.mes, count(*) as cuantos
from public.narrativas n, q
where n.user_id in (q.admin, q.duenio)
group by n.mes
having count(*) > 1;


-- =========================================================================
-- PASO B - respaldo
-- =========================================================================
--
-- Todo lo del admin, tal como está AHORA, en una sola tabla. Es data real: si
-- algo sale mal, de acá se reconstruye.
--
-- Cuando ya no haga falta:  drop table public.respaldo_013;

create table if not exists public.respaldo_013 (
    id          bigint generated always as identity primary key,
    tabla       text        not null,
    fila        jsonb       not null,
    guardado_en timestamptz not null default now()
);

-- Sin esto, el respaldo sería el agujero más grande de la base: en Supabase una
-- tabla nueva de `public` nace con permisos para anon y authenticated, así que
-- quedaría legible desde el navegador con la anon key. Y adentro está
-- exactamente lo que las policies protegen.
alter table public.respaldo_013 enable row level security;
revoke all on public.respaldo_013 from anon, authenticated;

do $$
declare
    admin_email text := 'arealegalesastarsa@gmail.com';
    admin_id    uuid;
    n           bigint;
begin
    select id into admin_id from auth.users where lower(email) = lower(admin_email);
    if admin_id is null then
        raise exception 'No existe ningún usuario con el email %.', admin_email;
    end if;

    delete from public.respaldo_013;   -- repetible sin duplicar

    insert into public.respaldo_013 (tabla, fila)
    select 'movimientos',   to_jsonb(t) from public.movimientos   t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'objetivos',     to_jsonb(t) from public.objetivos     t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'inversiones',   to_jsonb(t) from public.inversiones   t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'alertas',       to_jsonb(t) from public.alertas       t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'recordatorios', to_jsonb(t) from public.recordatorios t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'retos',         to_jsonb(t) from public.retos         t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'narrativas',    to_jsonb(t) from public.narrativas    t where t.user_id = admin_id;
    insert into public.respaldo_013 (tabla, fila)
    select 'usuarios_telegram', to_jsonb(t) from public.usuarios_telegram t where t.user_id = admin_id;

    select count(*) into n from public.respaldo_013;
    raise notice 'Respaldadas % filas del admin en public.respaldo_013.', n;
end $$;

-- Que el respaldo no quedó vacío. Si da 0, NO sigas: algo no cuadra.
select tabla, count(*) from public.respaldo_013 group by tabla order by 2 desc;


-- =========================================================================
-- PASO C - reasignar
-- =========================================================================
--
-- Un solo bloque, con los objetivos primero por el trigger. Todo o nada.

do $$
declare
    admin_email  text := 'arealegalesastarsa@gmail.com';   -- <<< DE quién salen
    duenio_email text := 'juanbanuss@gmail.com';           -- <<< A quién van
    admin_id     uuid;
    duenio_id    uuid;
    choques      int;
    n_obj bigint; n_mov bigint; n_inv bigint; n_ale bigint;
    n_rec bigint; n_ret bigint; n_nar bigint;
begin
    select id into admin_id  from auth.users where lower(email) = lower(admin_email);
    select id into duenio_id from auth.users where lower(email) = lower(duenio_email);

    if admin_id is null then
        raise exception 'No existe el usuario origen (%).', admin_email;
    end if;
    if duenio_id is null then
        raise exception 'No existe el usuario destino (%).', duenio_email;
    end if;
    -- Un typo que dejara los dos emails iguales convertiría todo esto en un
    -- no-op silencioso, y te quedarías creyendo que se movió algo.
    if admin_id = duenio_id then
        raise exception 'Origen y destino son el mismo usuario. Revisá los emails.';
    end if;

    -- El choque de narrativas, antes de tocar nada: si existe, el update
    -- reventaría contra el índice único y es mejor decirlo con nombre propio.
    select count(*) into choques
    from (
        select mes from public.narrativas
        where user_id in (admin_id, duenio_id)
        group by mes having count(*) > 1
    ) x;

    if choques > 0 then
        raise exception
            'Hay % mes(es) con narrativa en las DOS cuentas. El índice único '
            '(user_id, mes) no deja moverlas. Borrá a mano la del admin para '
            'esos meses y volvé a correr este paso.', choques;
    end if;

    -- 1) OBJETIVOS PRIMERO. El trigger movimientos_objetivo_propio exige que el
    --    objetivo de un movimiento sea del mismo dueño; si los movimientos se
    --    movieran antes, cada uno imputado a un objetivo sería rechazado.
    update public.objetivos set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_obj = row_count;

    -- 2) Ahora sí los movimientos: sus objetivos ya son del dueño nuevo.
    update public.movimientos set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_mov = row_count;

    -- 3) El resto no tiene dependencias entre sí; el orden da igual.
    update public.inversiones   set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_inv = row_count;
    update public.alertas       set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_ale = row_count;
    update public.recordatorios set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_rec = row_count;
    update public.retos         set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_ret = row_count;
    update public.narrativas    set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_nar = row_count;

    raise notice 'De % a %: % objetivos, % movimientos, % inversiones, '
                 '% alertas, % recordatorios, % retos, % narrativas.',
        admin_email, duenio_email, n_obj, n_mov, n_inv, n_ale, n_rec, n_ret, n_nar;
end $$;


-- ------------------------------------------------------- el vínculo de chat --
--
-- Aparte y comentado, porque no es un dato financiero y es una decisión tuya.
--
-- Si el chat de Telegram sigue colgando del admin, el próximo "gasté 5 lucas"
-- vuelve a crear movimientos ahí y estamos de nuevo en el mismo lugar. Moverlo
-- a la cuenta personal es lo que hace que el bot cargue donde corresponde.
--
-- Descomentar y correr:
/*
update public.usuarios_telegram
set user_id = (select id from auth.users where lower(email) = lower('juanbanuss@gmail.com'))
where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'));
*/


-- =========================================================================
-- PASO D - verificar
-- =========================================================================

-- (1) El admin tiene que quedar en CERO en todo. Es el punto 3 de lo que pediste.
with q as (
    select
        (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com')) as admin,
        (select id from auth.users where lower(email) = lower('juanbanuss@gmail.com'))         as duenio
)
select 'movimientos'   as tabla,
       (select count(*) from public.movimientos   where user_id = q.admin)  as le_queda_al_admin,
       (select count(*) from public.movimientos   where user_id = q.duenio) as tiene_el_duenio from q
union all
select 'objetivos',
       (select count(*) from public.objetivos     where user_id = q.admin),
       (select count(*) from public.objetivos     where user_id = q.duenio) from q
union all
select 'inversiones',
       (select count(*) from public.inversiones   where user_id = q.admin),
       (select count(*) from public.inversiones   where user_id = q.duenio) from q
union all
select 'alertas',
       (select count(*) from public.alertas       where user_id = q.admin),
       (select count(*) from public.alertas       where user_id = q.duenio) from q
union all
select 'recordatorios',
       (select count(*) from public.recordatorios where user_id = q.admin),
       (select count(*) from public.recordatorios where user_id = q.duenio) from q
union all
select 'retos',
       (select count(*) from public.retos         where user_id = q.admin),
       (select count(*) from public.retos         where user_id = q.duenio) from q
union all
select 'narrativas',
       (select count(*) from public.narrativas    where user_id = q.admin),
       (select count(*) from public.narrativas    where user_id = q.duenio) from q;


-- (2) Nada quedó sin dueño ni apuntando a un usuario que no existe. Vacío.
select 'movimientos' as tabla, count(*) as huerfanas from public.movimientos m
    where m.user_id is null or not exists (select 1 from auth.users u where u.id = m.user_id)
union all
select 'objetivos', count(*) from public.objetivos o
    where o.user_id is null or not exists (select 1 from auth.users u where u.id = o.user_id)
union all
select 'inversiones', count(*) from public.inversiones i
    where i.user_id is null or not exists (select 1 from auth.users u where u.id = i.user_id);


-- (3) Ningún movimiento quedó imputado a un objetivo de otra persona. Es lo que
-- vigila el trigger en las escrituras nuevas; esto lo confirma sobre lo que ya
-- está guardado, que el trigger nunca revisó. Tiene que dar vacío.
select m.id, m.descripcion, m.user_id as duenio_del_movimiento, o.user_id as duenio_del_objetivo
from public.movimientos m
join public.objetivos o on o.id = m.objetivo_id
where m.objetivo_id is not null
  and m.user_id <> o.user_id;


-- (4) La foto de conjunto: quién es quién y con cuánto se quedó.
select p.email, p.estado, p.rol,
       (select count(*) from public.movimientos m where m.user_id = p.user_id) as movimientos,
       (select count(*) from public.objetivos   o where o.user_id = p.user_id) as objetivos,
       t.chat_id
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;


-- =========================================================================
-- LAS FOTOS DE LOS OBJETIVOS: ESTO NO LAS MUEVE
-- =========================================================================
--
-- Si el PASO A contó fotos del admin, quedaron desconectadas: la ruta es
-- `<user_id>/<archivo>` y las policies de Storage comparan ese primer tramo
-- contra auth.uid(). El objetivo ahora es del dueño nuevo, pero la foto sigue
-- en la carpeta del admin, así que no la puede ver ninguno de los dos.
--
-- NO INTENTES ARREGLARLO CON UN UPDATE A storage.objects.name. La fila de esa
-- tabla es metadato: el archivo real vive aparte, bajo la ruta vieja. Renombrar
-- la fila desincroniza las dos cosas y el archivo queda inaccesible de verdad,
-- ahora sí sin vuelta.
--
-- La salida limpia, si son pocas: bajarlas del panel de Storage, y volver a
-- subirlas desde la app entrando como el dueño nuevo. Al subir, la app arma la
-- ruta con el uuid correcto y actualiza foto_path sola.
--
-- Y para que la pantalla no muestre una foto rota mientras tanto, soltar la
-- referencia (el archivo no se toca, solo se deja de apuntar):
/*
update public.objetivos
set foto_path = null
where foto_path like
      (select id::text from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com')) || '/%';
*/
