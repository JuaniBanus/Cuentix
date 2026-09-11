-- Categorias gestionables por cada usuario.
--
-- EL PROBLEMA
-- La IA inventaba la categoria en el momento de parsear el mensaje, asi que el
-- mismo rubro entraba un dia como "super" y al otro como "supermercado". Los
-- graficos mostraban dos porciones donde hay una sola, y "cuanto gaste en
-- super" devolvia cero porque el filtro compara con eq contra "supermercado".
--
-- QUE ES ESTA TABLA, Y QUE NO ES
-- Es el VOCABULARIO del que la IA puede elegir. NO es la fuente de verdad del
-- historial: movimientos.categoria sigue siendo texto y no lleva foreign key.
-- La web (web/js/donut.js, comparacion.js, insights.js, narrativa.js) lo lee
-- como string y se sube a mano a Hostinger, mientras que el backend se
-- despliega solo en Render: cambiarle el contrato a movimientos dejaria la web
-- rota hasta la proxima subida manual.
--
-- Efecto lateral buscado: borrar una categoria no rompe ningun grafico ni
-- pierde un movimiento. La etiqueta vieja sigue escrita en las filas que ya
-- existen; lo unico que cambia es que la IA deja de ofrecerla.
--
-- Idempotente: se puede volver a correr sin romper nada.


create table if not exists public.categorias (
    id        uuid        primary key default gen_random_uuid(),

    -- NULL = categoria base, la ve todo el mundo.
    -- Con valor = privada de ese usuario, no la ve nadie mas.
    --
    -- A proposito NO lleva `default auth.uid()` como movimientos.user_id: el
    -- bot escribe con service_role, donde auth.uid() es NULL, asi que un
    -- olvido no crearia una fila privada sino una BASE PARA TODOS. Sin default,
    -- el _exigir(user_id) de app/db.py corta antes de llegar aca.
    user_id   uuid        references auth.users (id) on delete cascade,

    -- Es exactamente la cadena que termina en movimientos.categoria, en
    -- minusculas. Tiene que coincidir letra a letra o el filtro .eq() de
    -- app/db.py no matchea nunca.
    --
    -- Las tildes se admiten y se conservan: si una fila vieja dice "educación",
    -- su categoria tiene que decir "educación" tambien, o dejarian de ser la
    -- misma cosa. La comparacion sin tildes la hace app/categorias.py al
    -- emparejar lo que dijo el usuario, no la base.
    nombre    text        not null
                          check (char_length(nombre) between 1 and 60
                                 and nombre = lower(nombre)),

    -- Para que clase de movimiento sirve. Un gasto nunca ve las de ingreso.
    -- Sin esto, pedirle a la IA que elija de una lista cerrada convertiria
    -- "cobre el sueldo" en una pregunta.
    tipo      text        not null default 'gasto'
                          check (tipo in ('gasto', 'ingreso', 'ahorro', 'inversion')),

    emoji     text        check (emoji is null or char_length(emoji) between 1 and 8),

    creado_en timestamptz not null default now()
);


-- Dos indices parciales en vez de un unique comun: un unique normal no
-- distingue NULLs, asi que (null, 'gasto', 'comida') y (null, 'gasto',
-- 'comida') convivirian sin que Postgres se queje.
create unique index if not exists categorias_base_idx
    on public.categorias (tipo, nombre) where user_id is null;

create unique index if not exists categorias_propias_idx
    on public.categorias (user_id, tipo, nombre) where user_id is not null;

-- El bot lee "las base mas las mias" en cada mensaje.
create index if not exists categorias_user_idx
    on public.categorias (user_id, tipo);


-- Un usuario no puede crear una categoria que se llame igual que una base:
-- quedarian dos filas peleando por el mismo texto en movimientos.categoria y
-- ninguna consulta podria decir cual es cual. Esto no lo puede hacer un unique
-- index, porque son dos indices distintos.
create or replace function public.categoria_no_pisa_base()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if new.user_id is not null and exists (
        select 1 from public.categorias
        where user_id is null
          and tipo   = new.tipo
          and nombre = new.nombre
    ) then
        raise exception 'La categoria % ya existe como base.', new.nombre;
    end if;
    return new;
end;
$$;

drop trigger if exists categorias_no_pisan_base on public.categorias;

create trigger categorias_no_pisan_base
    before insert or update of nombre, tipo, user_id on public.categorias
    for each row execute function public.categoria_no_pisa_base();


-- ---------------------------------------------------------------------------
-- RLS
--
-- La gestion es del bot, que escribe con service_role y saltea RLS por diseño.
-- La clave anon (la que esta a la vista en la web) queda en SOLO LECTURA: el
-- grant de escritura no se otorga. Las policies de insert/update/delete se
-- escriben igual porque son las correctas el dia que la web tenga su ABM, y
-- asi habilitarlo es un grant de una linea sin volver a pensar las reglas.
-- ---------------------------------------------------------------------------

alter table public.categorias enable row level security;

revoke all    on public.categorias from anon, authenticated;
grant  select on public.categorias to   authenticated;

drop policy if exists "categorias: ver las base y las propias" on public.categorias;
drop policy if exists "categorias: crear propias"              on public.categorias;
drop policy if exists "categorias: editar las propias"         on public.categorias;
drop policy if exists "categorias: borrar las propias"         on public.categorias;

create policy "categorias: ver las base y las propias"
    on public.categorias for select
    to authenticated
    using (
        (user_id is null or user_id = (select auth.uid()))
        and (select public.es_activo())
    );

-- En las filas base user_id es NULL, asi que `user_id = auth.uid()` da NULL,
-- no true: las base quedan intocables sin escribir una regla aparte.
create policy "categorias: crear propias"
    on public.categorias for insert
    to authenticated
    with check (user_id = (select auth.uid()) and (select public.es_activo()));

create policy "categorias: editar las propias"
    on public.categorias for update
    to authenticated
    using      (user_id = (select auth.uid()) and (select public.es_activo()))
    with check (user_id = (select auth.uid()) and (select public.es_activo()));

create policy "categorias: borrar las propias"
    on public.categorias for delete
    to authenticated
    using (user_id = (select auth.uid()) and (select public.es_activo()));


-- ---------------------------------------------------------------------------
-- El set base
--
-- Pensado para Argentina: nafta separada de transporte (son dos decisiones
-- distintas), expensas separadas de alquiler, gimnasio e impuestos con renglon
-- propio porque el monotributo y el ABL aparecen todos los meses.
--
-- "dolares" esta en ahorro Y en inversion a proposito: comprar dolares para
-- guardar y para especular no son lo mismo, y el tipo los desambigua.
--
-- "otros" existe una vez por tipo. Es la unica categoria que el bot da por
-- garantizada: es donde cae un gasto mientras pregunta a donde va de verdad.
-- ---------------------------------------------------------------------------

insert into public.categorias (user_id, tipo, nombre, emoji) values
    (null, 'gasto',     'supermercado',        '🛒'),
    (null, 'gasto',     'comida',              '🍔'),
    (null, 'gasto',     'transporte',          '🚕'),
    (null, 'gasto',     'nafta',               '⛽'),
    (null, 'gasto',     'servicios',           '💡'),
    (null, 'gasto',     'alquiler',            '🏠'),
    (null, 'gasto',     'expensas',            '🏢'),
    (null, 'gasto',     'salud',               '💊'),
    (null, 'gasto',     'educacion',           '📚'),
    (null, 'gasto',     'ropa',                '👕'),
    (null, 'gasto',     'tecnologia',          '💻'),
    (null, 'gasto',     'ocio',                '🎬'),
    (null, 'gasto',     'gimnasio',            '🏋️'),
    (null, 'gasto',     'suscripciones',       '📺'),
    (null, 'gasto',     'viajes',              '✈️'),
    (null, 'gasto',     'mascotas',            '🐾'),
    (null, 'gasto',     'regalos',             '🎁'),
    (null, 'gasto',     'impuestos',           '🧾'),
    (null, 'gasto',     'hogar',               '🛋️'),
    (null, 'gasto',     'cuidado personal',    '✂️'),
    (null, 'gasto',     'otros',               '📦'),

    (null, 'ingreso',   'sueldo',              '💼'),
    (null, 'ingreso',   'aguinaldo',           '🎄'),
    (null, 'ingreso',   'freelance',           '🧑‍💻'),
    (null, 'ingreso',   'ventas',              '🏷️'),
    (null, 'ingreso',   'alquileres',          '🏘️'),
    (null, 'ingreso',   'intereses',           '🏦'),
    (null, 'ingreso',   'reintegros',          '🔄'),
    (null, 'ingreso',   'otros',               '📥'),

    (null, 'ahorro',    'plazo fijo',          '🏦'),
    (null, 'ahorro',    'dolares',             '💵'),
    (null, 'ahorro',    'fondo de emergencia', '🛟'),
    (null, 'ahorro',    'otros',               '🐖'),

    (null, 'inversion', 'acciones',            '📈'),
    (null, 'inversion', 'cedears',             '🌎'),
    (null, 'inversion', 'cripto',              '🪙'),
    (null, 'inversion', 'bonos',               '📜'),
    (null, 'inversion', 'fci',                 '📊'),
    (null, 'inversion', 'dolares',             '💵'),
    (null, 'inversion', 'otros',               '📦')
on conflict (tipo, nombre) where user_id is null do nothing;


-- ---------------------------------------------------------------------------
-- Importar lo que ya existe
--
-- Toda etiqueta que este hoy en movimientos y no sea una base pasa a ser una
-- categoria PROPIA de su dueño. Nada se reescribe: ni un movimiento cambia de
-- etiqueta, ni un grafico cambia de forma. Lo unico que pasa es que la IA
-- vuelve a poder elegir todo lo que ya venias usando.
--
-- Unificar sinonimos ("super" -> "supermercado") es otra cosa, es destructivo,
-- y va aparte en 020_categorias_unificar.sql.
-- ---------------------------------------------------------------------------

insert into public.categorias (user_id, tipo, nombre)
select distinct
    m.user_id,
    m.tipo,
    lower(trim(m.categoria))
from public.movimientos m
where m.user_id is not null
  and m.categoria is not null
  and char_length(trim(m.categoria)) between 1 and 60
  and not exists (
      select 1 from public.categorias c
      where c.user_id is null
        and c.tipo   = m.tipo
        and c.nombre = lower(trim(m.categoria))
  )
on conflict (user_id, tipo, nombre) where user_id is not null do nothing;


-- ---------------------------------------------------------------------------
-- Comprobaciones. No modifican nada.
-- ---------------------------------------------------------------------------

-- Cuantas quedaron, base y propias, por tipo.
select
    tipo,
    count(*) filter (where user_id is null)     as base,
    count(*) filter (where user_id is not null) as propias
from public.categorias
group by tipo
order by tipo;

-- Movimientos cuya etiqueta no quedo en el vocabulario de su dueño.
-- TIENE QUE DAR CERO. Si da otra cosa, algo del import fallo y el bot va a
-- preguntar por categorias que el usuario ya venia usando.
select count(*) as movimientos_huerfanos
from public.movimientos m
where m.user_id is not null
  and not exists (
      select 1 from public.categorias c
      where c.tipo   = m.tipo
        and c.nombre = lower(trim(m.categoria))
        and (c.user_id is null or c.user_id = m.user_id)
  );
