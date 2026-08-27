-- ¿El alta automática de perfiles funciona? Verificación y red de contención.


select
    t.tgname as trigger,
    case t.tgenabled
        when 'O' then 'habilitado'
        when 'D' then 'DESHABILITADO'
        when 'R' then 'solo en réplica'
        when 'A' then 'siempre'
    end as estado,
    pg_get_triggerdef(t.oid) as definicion
from pg_trigger t
where t.tgrelid = 'auth.users'::regclass
  and not t.tgisinternal;

select p.proname as funcion,
       p.prosecdef as es_security_definer,
       p.proconfig as search_path
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname = 'perfil_para_usuario_nuevo';


begin;

    insert into auth.users (id, email)
    values (gen_random_uuid(), 'prueba-trigger@ejemplo.com');

    select user_id, email, estado, rol, debe_cambiar_password, creado_en
    from public.perfiles
    where email = 'prueba-trigger@ejemplo.com';

rollback;

select
    (select count(*) from auth.users       where email = 'prueba-trigger@ejemplo.com') as usuario_quedo,
    (select count(*) from public.perfiles  where email = 'prueba-trigger@ejemplo.com') as perfil_quedo;


select u.id, u.email, u.created_at
from auth.users u
left join public.perfiles p on p.user_id = u.id
where p.user_id is null
order by u.created_at;

insert into public.perfiles (user_id, email)
select u.id, u.email
from auth.users u
left join public.perfiles p on p.user_id = u.id
where p.user_id is null
  and u.email is not null
on conflict (user_id) do nothing;


select p.email, p.estado, p.rol, p.debe_cambiar_password, t.chat_id
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;


