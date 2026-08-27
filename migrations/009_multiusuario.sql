-- Multiusuario con aislamiento total.


create table if not exists public.perfiles (
    user_id               uuid        primary key
                                      references auth.users (id) on delete cascade,

    email                 text        not null,

    estado                text        not null default 'pendiente'
                                      check (estado in ('activo', 'pausado', 'pendiente')),

    rol                   text        not null default 'usuario'
                                      check (rol in ('usuario', 'superusuario')),

    debe_cambiar_password boolean     not null default true,

    creado_en             timestamptz not null default now()
);

create unique index if not exists perfiles_email_idx on public.perfiles (lower(email));


create or replace function public.perfil_para_usuario_nuevo()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    insert into public.perfiles (user_id, email)
    values (new.id, new.email)
    on conflict (user_id) do update set email = excluded.email;
    return new;
end;
$$;

drop trigger if exists perfiles_alta on auth.users;

create trigger perfiles_alta
    after insert or update of email on auth.users
    for each row execute function public.perfil_para_usuario_nuevo();


create or replace function public.es_activo()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from public.perfiles
        where user_id = auth.uid() and estado = 'activo'
    );
$$;

create or replace function public.es_superusuario()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from public.perfiles
        where user_id = auth.uid()
          and rol = 'superusuario'
          and estado = 'activo'
    );
$$;

revoke execute on function public.es_activo()       from public;
revoke execute on function public.es_superusuario() from public;
grant  execute on function public.es_activo()       to authenticated;
grant  execute on function public.es_superusuario() to authenticated;


revoke all on public.perfiles from anon, authenticated;

grant select                        on public.perfiles to authenticated;
grant update (debe_cambiar_password) on public.perfiles to authenticated;


alter table public.perfiles enable row level security;

drop policy if exists "perfiles: ver el propio"     on public.perfiles;
drop policy if exists "perfiles: el super ve todos" on public.perfiles;
drop policy if exists "perfiles: editar el propio"  on public.perfiles;

create policy "perfiles: ver el propio"
    on public.perfiles for select
    to authenticated
    using ((select auth.uid()) = user_id);

create policy "perfiles: el super ve todos"
    on public.perfiles for select
    to authenticated
    using ((select public.es_superusuario()));

create policy "perfiles: editar el propio"
    on public.perfiles for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);


create or replace function public.admin_cambiar_estado(
    p_user_id uuid,
    p_estado  text
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if not public.es_superusuario() then
        raise exception 'Solo un superusuario puede cambiar el estado de una cuenta.';
    end if;

    if p_estado not in ('activo', 'pausado', 'pendiente') then
        raise exception 'Estado inválido: %', p_estado;
    end if;

    if p_user_id = auth.uid() then
        raise exception 'No podés cambiar tu propio estado.';
    end if;

    update public.perfiles set estado = p_estado where user_id = p_user_id;
end;
$$;

revoke execute on function public.admin_cambiar_estado(uuid, text) from public, anon;
grant  execute on function public.admin_cambiar_estado(uuid, text) to authenticated;


create table if not exists public.usuarios_telegram (
    chat_id    bigint      primary key,

    user_id    uuid        not null
                           references auth.users (id) on delete cascade,

    alias      text        check (alias is null or char_length(alias) between 1 and 60),

    creado_en  timestamptz not null default now()
);

create index if not exists usuarios_telegram_user_idx
    on public.usuarios_telegram (user_id);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'usuarios_telegram_perfil_fk'
    ) then
        alter table public.usuarios_telegram
            add constraint usuarios_telegram_perfil_fk
            foreign key (user_id) references public.perfiles (user_id)
            on delete cascade;
    end if;
end $$;

alter table public.usuarios_telegram enable row level security;

drop policy if exists "telegram: ver los propios" on public.usuarios_telegram;

create policy "telegram: ver los propios"
    on public.usuarios_telegram for select
    to authenticated
    using ((select auth.uid()) = user_id);


alter table public.movimientos
    add column if not exists user_id uuid references auth.users (id) on delete cascade;


do $$
declare
    mi_email  text := 'arealegalesastarsa@gmail.com';
    mi_id     uuid;
    n_mov     bigint;
    n_rec     bigint;
    n_ret     bigint;
begin
    select id into mi_id from auth.users where lower(email) = lower(mi_email);

    if mi_id is null then
        raise exception
            'No hay ningún usuario con el email %. Revisá Authentication -> Users.', mi_email;
    end if;

    insert into public.perfiles (user_id, email, estado, rol, debe_cambiar_password)
    values (mi_id, mi_email, 'activo', 'superusuario', false)
    on conflict (user_id) do update
        set estado = 'activo',
            rol    = 'superusuario';

    update public.movimientos set user_id = mi_id where user_id is null;
    get diagnostics n_mov = row_count;

    update public.recordatorios set user_id = mi_id where user_id is null;
    get diagnostics n_rec = row_count;

    update public.retos set user_id = mi_id where user_id is null;
    get diagnostics n_ret = row_count;

    raise notice 'Asignado a % (%): % movimientos, % recordatorios, % retos.',
        mi_email, mi_id, n_mov, n_rec, n_ret;
end $$;


alter table public.movimientos
    alter column user_id set default auth.uid();

alter table public.movimientos
    alter column user_id set not null;


create index if not exists movimientos_user_fecha_idx
    on public.movimientos (user_id, fecha desc, id desc);

create index if not exists movimientos_user_tipo_fecha_idx
    on public.movimientos (user_id, tipo, fecha desc);


create or replace function public.validar_objetivo_propio()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if new.objetivo_id is not null and not exists (
        select 1 from public.objetivos o
        where o.id = new.objetivo_id and o.user_id = new.user_id
    ) then
        raise exception 'El objetivo % no pertenece al usuario %.',
            new.objetivo_id, new.user_id;
    end if;
    return new;
end;
$$;

drop trigger if exists movimientos_objetivo_propio on public.movimientos;

create trigger movimientos_objetivo_propio
    before insert or update of objetivo_id, user_id on public.movimientos
    for each row execute function public.validar_objetivo_propio();


alter table public.recordatorios alter column user_id set not null;
alter table public.retos         alter column user_id set not null;


alter table public.movimientos enable row level security;

drop policy if exists "movimientos: leer con sesión"    on public.movimientos;
drop policy if exists "movimientos: leer los propios"   on public.movimientos;
drop policy if exists "movimientos: crear propios"      on public.movimientos;
drop policy if exists "movimientos: editar los propios" on public.movimientos;
drop policy if exists "movimientos: borrar los propios" on public.movimientos;

create policy "movimientos: leer los propios"
    on public.movimientos for select
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "movimientos: crear propios"
    on public.movimientos for insert
    to authenticated
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "movimientos: editar los propios"
    on public.movimientos for update
    to authenticated
    using      ((select auth.uid()) = user_id and (select public.es_activo()))
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "movimientos: borrar los propios"
    on public.movimientos for delete
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));


alter table public.objetivos enable row level security;

drop policy if exists "objetivos: leer los propios"   on public.objetivos;
drop policy if exists "objetivos: crear propios"      on public.objetivos;
drop policy if exists "objetivos: editar los propios" on public.objetivos;
drop policy if exists "objetivos: borrar los propios" on public.objetivos;

create policy "objetivos: leer los propios"
    on public.objetivos for select
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "objetivos: crear propios"
    on public.objetivos for insert
    to authenticated
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "objetivos: editar los propios"
    on public.objetivos for update
    to authenticated
    using      ((select auth.uid()) = user_id and (select public.es_activo()))
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "objetivos: borrar los propios"
    on public.objetivos for delete
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));


alter table public.inversiones enable row level security;

drop policy if exists "inversiones: leer las propias"   on public.inversiones;
drop policy if exists "inversiones: crear propias"      on public.inversiones;
drop policy if exists "inversiones: editar las propias" on public.inversiones;
drop policy if exists "inversiones: borrar las propias" on public.inversiones;

create policy "inversiones: leer las propias"
    on public.inversiones for select
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "inversiones: crear propias"
    on public.inversiones for insert
    to authenticated
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "inversiones: editar las propias"
    on public.inversiones for update
    to authenticated
    using      ((select auth.uid()) = user_id and (select public.es_activo()))
    with check ((select auth.uid()) = user_id and (select public.es_activo()));

create policy "inversiones: borrar las propias"
    on public.inversiones for delete
    to authenticated
    using ((select auth.uid()) = user_id and (select public.es_activo()));


select 'movimientos'   as tabla, count(*) as sin_dueno from public.movimientos   where user_id is null
union all
select 'objetivos',    count(*) from public.objetivos    where user_id is null
union all
select 'inversiones',  count(*) from public.inversiones  where user_id is null;

select relname as tabla_sin_rls
from pg_class
where relnamespace = 'public'::regnamespace
  and relkind = 'r'
  and not relrowsecurity;

select tablename, policyname, cmd, roles, qual, with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('movimientos', 'objetivos', 'inversiones',
                    'perfiles', 'usuarios_telegram')
order by tablename, cmd;


