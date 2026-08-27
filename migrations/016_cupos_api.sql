-- Cupos de consumo de APIs externas, por usuario y por dia.
--
-- RLS activo y sin policies a proposito: solo la clave de servicio las toca. Con
-- una policy por dueno, el usuario podria poner su propio contador en cero.

create table if not exists public.consumo_api (
    user_id    uuid        not null references auth.users (id) on delete cascade,
    dia        date        not null,
    servicio   text        not null,
    refrescos  integer     not null default 0,
    unidades   integer     not null default 0,
    tickers    text[]      not null default '{}',
    primary key (user_id, dia, servicio)
);

create table if not exists public.consumo_global (
    dia       date    not null,
    servicio  text    not null,
    unidades  integer not null default 0,
    primary key (dia, servicio)
);

alter table public.consumo_api    enable row level security;
alter table public.consumo_global enable row level security;

create index if not exists consumo_api_dia_idx on public.consumo_api (dia);


-- Reserva cupo y lo cobra en la misma transaccion. Si no alcanza, no gasta:
-- devuelve el motivo para que quien llama sirva el precio cacheado.
create or replace function public.consumir_cupo(
    p_user_id        uuid,
    p_servicio       text,
    p_unidades       integer,
    p_refrescos      integer,
    p_tickers        text[],
    p_tope_refrescos integer,
    p_tope_unidades  integer,
    p_tope_global    integer
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_hoy      date := (now() at time zone 'utc')::date;
    v_fila     public.consumo_api%rowtype;
    v_global   integer;
    v_tickers  text[];
begin
    insert into public.consumo_api (user_id, dia, servicio)
    values (p_user_id, v_hoy, p_servicio)
    on conflict (user_id, dia, servicio) do nothing;

    select * into v_fila
    from public.consumo_api
    where user_id = p_user_id and dia = v_hoy and servicio = p_servicio
    for update;

    insert into public.consumo_global (dia, servicio)
    values (v_hoy, p_servicio)
    on conflict (dia, servicio) do nothing;

    select unidades into v_global
    from public.consumo_global
    where dia = v_hoy and servicio = p_servicio
    for update;

    v_tickers := array(
        select distinct unnest(v_fila.tickers || coalesce(p_tickers, '{}'))
    );

    if v_fila.refrescos + p_refrescos > p_tope_refrescos then
        return jsonb_build_object('permitido', false, 'motivo', 'refrescos',
                                  'refrescos', v_fila.refrescos, 'unidades', v_fila.unidades,
                                  'global', v_global, 'tickers', array_length(v_tickers, 1));
    end if;

    if v_fila.unidades + p_unidades > p_tope_unidades then
        return jsonb_build_object('permitido', false, 'motivo', 'unidades',
                                  'refrescos', v_fila.refrescos, 'unidades', v_fila.unidades,
                                  'global', v_global, 'tickers', array_length(v_tickers, 1));
    end if;

    if v_global + p_unidades > p_tope_global then
        return jsonb_build_object('permitido', false, 'motivo', 'global',
                                  'refrescos', v_fila.refrescos, 'unidades', v_fila.unidades,
                                  'global', v_global, 'tickers', array_length(v_tickers, 1));
    end if;

    update public.consumo_api
       set refrescos = refrescos + p_refrescos,
           unidades  = unidades + p_unidades,
           tickers   = v_tickers
     where user_id = p_user_id and dia = v_hoy and servicio = p_servicio;

    update public.consumo_global
       set unidades = unidades + p_unidades
     where dia = v_hoy and servicio = p_servicio;

    return jsonb_build_object('permitido', true, 'motivo', null,
                              'refrescos', v_fila.refrescos + p_refrescos,
                              'unidades', v_fila.unidades + p_unidades,
                              'global', v_global + p_unidades,
                              'tickers', array_length(v_tickers, 1));
end;
$$;

revoke execute on function public.consumir_cupo(uuid, text, integer, integer, text[], integer, integer, integer)
    from public, anon, authenticated;


-- Cuanto le queda a un usuario hoy. Solo lectura, para mostrarlo en pantalla.
create or replace function public.cupo_restante(p_user_id uuid, p_servicio text)
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'refrescos', coalesce(c.refrescos, 0),
        'unidades',  coalesce(c.unidades, 0),
        'tickers',   coalesce(array_length(c.tickers, 1), 0)
    )
    from (select 1) z
    left join public.consumo_api c
      on c.user_id = p_user_id
     and c.dia = (now() at time zone 'utc')::date
     and c.servicio = p_servicio;
$$;

revoke execute on function public.cupo_restante(uuid, text) from public, anon, authenticated;


-- Purga el historico de consumo, que no sirve pasados unos dias.
create or replace function public.purgar_consumo(p_dias integer default 30)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
    delete from public.consumo_api
     where dia < (now() at time zone 'utc')::date - p_dias;
$$;

revoke execute on function public.purgar_consumo(integer) from public, anon, authenticated;
