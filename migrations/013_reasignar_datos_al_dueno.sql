-- Devolverle al usuario real los datos que la 009 le asignó al administrador.


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


select fecha, tipo, monto, moneda, categoria, descripcion
from public.movimientos
where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
order by fecha desc;


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


create table if not exists public.respaldo_013 (
    id          bigint generated always as identity primary key,
    tabla       text        not null,
    fila        jsonb       not null,
    guardado_en timestamptz not null default now()
);

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

    delete from public.respaldo_013;

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

select tabla, count(*) from public.respaldo_013 group by tabla order by 2 desc;


do $$
declare
    admin_email  text := 'arealegalesastarsa@gmail.com';
    duenio_email text := 'juanbanuss@gmail.com';
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
    if admin_id = duenio_id then
        raise exception 'Origen y destino son el mismo usuario. Revisá los emails.';
    end if;

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

    update public.objetivos set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_obj = row_count;

    update public.movimientos set user_id = duenio_id where user_id = admin_id;
    get diagnostics n_mov = row_count;

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


select 'movimientos' as tabla, count(*) as huerfanas from public.movimientos m
    where m.user_id is null or not exists (select 1 from auth.users u where u.id = m.user_id)
union all
select 'objetivos', count(*) from public.objetivos o
    where o.user_id is null or not exists (select 1 from auth.users u where u.id = o.user_id)
union all
select 'inversiones', count(*) from public.inversiones i
    where i.user_id is null or not exists (select 1 from auth.users u where u.id = i.user_id);


select m.id, m.descripcion, m.user_id as duenio_del_movimiento, o.user_id as duenio_del_objetivo
from public.movimientos m
join public.objetivos o on o.id = m.objetivo_id
where m.objetivo_id is not null
  and m.user_id <> o.user_id;


select p.email, p.estado, p.rol,
       (select count(*) from public.movimientos m where m.user_id = p.user_id) as movimientos,
       (select count(*) from public.objetivos   o where o.user_id = p.user_id) as objetivos,
       t.chat_id
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;


