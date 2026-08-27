-- ##  NO CORRAS ESTE ARCHIVO. QUEDO OBSOLETO.                            ##


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

select fecha, tipo, monto, moneda, categoria, descripcion
from public.movimientos
where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
order by fecha desc
limit 30;


create table if not exists public.respaldo_010 (
    id          bigint generated always as identity primary key,
    tabla       text        not null,
    fila        jsonb       not null,
    guardado_en timestamptz not null default now()
);

alter table public.respaldo_010 enable row level security;
revoke all on public.respaldo_010 from anon, authenticated;

do $$
declare
    mi_email text := 'arealegalesastarsa@gmail.com';
    mi_id    uuid;
    n        bigint;
begin
    select id into mi_id from auth.users where lower(email) = lower(mi_email);
    if mi_id is null then
        raise exception 'No existe ningún usuario con el email %.', mi_email;
    end if;

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


do $$
declare
    mi_email text := 'arealegalesastarsa@gmail.com';
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

    delete from storage.objects
    where bucket_id = 'objetivos'
      and (storage.foldername(name))[1] = mi_id::text;
    get diagnostics n_fot = row_count;

    delete from public.usuarios_telegram where user_id = mi_id;
    get diagnostics n_tel = row_count;

    raise notice
        'Borrado de %: % movimientos, % objetivos, % inversiones, % alertas, '
        '% recordatorios, % retos, % narrativas, % fotos, % vínculo(s) de Telegram.',
        mi_email, n_mov, n_obj, n_inv, n_ale, n_rec, n_ret, n_nar, n_fot, n_tel;
end $$;


select 'movimientos'   as tabla, count(*) as le_queda from public.movimientos   where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'objetivos',    count(*) from public.objetivos    where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'inversiones',  count(*) from public.inversiones  where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'))
union all
select 'telegram',     count(*) from public.usuarios_telegram where user_id = (select id from auth.users where lower(email) = lower('arealegalesastarsa@gmail.com'));

select email, estado, rol, debe_cambiar_password
from public.perfiles
where lower(email) = lower('arealegalesastarsa@gmail.com');

select p.email, p.estado, p.rol, t.chat_id, t.alias
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;
