-- Multiusuario con aislamiento total.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.
--
-- =========================================================================
-- LEER ESTO ANTES DE CORRER
-- =========================================================================
--
-- 1) En el PASO 0 hay un email hardcodeado. Es el que se queda con TODOS los
--    datos que ya existen y el que queda como superusuario. Si no es el tuyo,
--    cambialo ahí antes de correr. Si no existe en auth.users, el script se
--    aborta entero sin tocar nada (raise exception dentro de un DO).
--
-- 2) Después de correr esto, `movimientos.user_id` es NOT NULL. El bot escribe
--    con service_role, donde auth.uid() es NULL, así que sus inserts van a
--    fallar hasta que app/db.py mande el user_id explícito. El orden de
--    despliegue está al final del archivo, en "QUÉ HAY QUE TOCAR EN EL CÓDIGO".
--
-- 3) RLS protege a la anon key del navegador. NO protege al bot: service_role
--    saltea RLS por diseño. El aislamiento del lado del bot lo da
--    `usuarios_telegram` + filtrar en Python. Las dos mitades son necesarias.
--
--
-- ORDEN DEL ARCHIVO (importa: cada paso depende del anterior)
--   PASO 0 - perfiles + funciones de ayuda
--   PASO 1 - usuarios_telegram (chat_id <-> user_id)
--   PASO 2 - movimientos.user_id (agregar, rellenar, exigir)
--   PASO 3 - huérfanas en recordatorios y retos
--   PASO 4 - RLS estricto en movimientos, objetivos, inversiones
--   PASO 5 - verificación, incluido un simulacro de intrusión


-- =========================================================================
-- PASO 0 - perfiles
-- =========================================================================
--
-- Por qué una tabla aparte y no los metadatos de auth.users: `raw_user_meta_data`
-- lo puede editar el propio usuario desde el navegador con updateUser(). Un rol
-- guardado ahí es un rol que cada uno se autoasigna. Acá el rol vive en una
-- tabla nuestra, con RLS y sin permiso de escritura sobre esa columna.

create table if not exists public.perfiles (
    -- PK y FK a la vez: un perfil es un usuario, no hay perfil sin cuenta.
    -- El cascade evita que borrar un usuario deje el perfil colgado.
    user_id               uuid        primary key
                                      references auth.users (id) on delete cascade,

    -- Copia de auth.users.email, mantenida por el trigger de más abajo. Es una
    -- copia y no la fuente: sirve para listar usuarios sin tener que consultar
    -- el esquema auth (que la anon key no puede leer nunca).
    email                 text        not null,

    -- pendiente: la cuenta existe pero todavía no la habilitaste.
    -- activo:    puede entrar y ver lo suyo.
    -- pausado:   la cuenta sigue existiendo, con sus datos, pero no lee nada.
    -- El estado NO es decorativo: las policies del PASO 4 lo miran. Un usuario
    -- pausado que conserve su JWT sigue sin ver una sola fila.
    estado                text        not null default 'pendiente'
                                      check (estado in ('activo', 'pausado', 'pendiente')),

    -- superusuario habilita leer la lista de perfiles y cambiar estados, nada
    -- más. No da acceso a los datos de nadie: no existe ninguna policy que
    -- deje ver movimientos ajenos, ni siquiera siendo superusuario.
    rol                   text        not null default 'usuario'
                                      check (rol in ('usuario', 'superusuario')),

    -- Para el alta con contraseña provisoria: la web lo lee y, si está en true,
    -- manda a cambiarla antes de mostrar nada.
    debe_cambiar_password boolean     not null default true,

    creado_en             timestamptz not null default now()
);

-- auth.users ya garantiza el email único; este índice es para que la lista de
-- administración pueda buscar por email sin escanear.
create unique index if not exists perfiles_email_idx on public.perfiles (lower(email));


-- --------------------------------------------------------------- trigger ---
-- Alta automática: cada usuario nuevo de auth.users nace con perfil. Sin esto
-- habría que acordarse de crearlo a mano y un usuario sin perfil quedaría sin
-- poder leer nada (las policies exigen perfil activo), con un error mudo.
--
-- security definer porque el trigger corre en el contexto de quien se registra,
-- que no tiene permiso de escribir en perfiles. El search_path fijo es
-- obligatorio en toda función security definer: sin él, alguien que pueda
-- crear objetos en otro esquema puede secuestrar los nombres de adentro.
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

-- También en UPDATE OF email: si cambiás el mail de la cuenta, la copia sigue.
create trigger perfiles_alta
    after insert or update of email on auth.users
    for each row execute function public.perfil_para_usuario_nuevo();


-- ------------------------------------------------ funciones de contexto ----
--
-- Las policies necesitan preguntar "¿el que consulta está activo?", y eso vive
-- en perfiles. Consultar perfiles adentro de una policy DE perfiles sería
-- recursión infinita. Estas funciones son security definer: corren como el
-- dueño de la tabla, que no pasa por RLS, así que cortan la recursión.
--
-- Devuelven un booleano sobre QUIEN LLAMA y no aceptan parámetros: no hay forma
-- de usarlas para preguntar por otro.

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
          and estado = 'activo'   -- un superusuario pausado no es superusuario
    );
$$;

revoke execute on function public.es_activo()       from public;
revoke execute on function public.es_superusuario() from public;
grant  execute on function public.es_activo()       to authenticated;
grant  execute on function public.es_superusuario() to authenticated;


-- ------------------------------------------------- permisos de columna -----
--
-- Esto es lo que RLS NO puede hacer. RLS decide qué FILAS tocás, no qué
-- COLUMNAS. Si hubiera una policy de UPDATE sobre la fila propia, cualquiera
-- podría mandar {"rol": "superusuario"} sobre su propio perfil y RLS lo
-- aprobaría, porque la fila es suya.
--
-- Supabase le da todos los permisos a `authenticated` sobre las tablas nuevas
-- de public. Acá se los sacamos y devolvemos solo dos: leer, y escribir UNA
-- columna. Un UPDATE que toque cualquier otra es rechazado por el motor antes
-- de llegar a RLS.
revoke all on public.perfiles from anon, authenticated;

grant select                        on public.perfiles to authenticated;
grant update (debe_cambiar_password) on public.perfiles to authenticated;


-- ------------------------------------------------------------------ RLS ----
alter table public.perfiles enable row level security;

drop policy if exists "perfiles: ver el propio"     on public.perfiles;
drop policy if exists "perfiles: el super ve todos" on public.perfiles;
drop policy if exists "perfiles: editar el propio"  on public.perfiles;

-- Cada uno ve su perfil. Sin condición de estado: un usuario pausado tiene que
-- poder leer su propio perfil, porque es de ahí que la web saca el motivo por
-- el que no ve nada y muestra "tu cuenta está pausada" en vez de un dashboard
-- vacío sin explicación.
create policy "perfiles: ver el propio"
    on public.perfiles for select
    to authenticated
    using ((select auth.uid()) = user_id);

-- El superusuario ve la lista completa: email, estado, rol. Nada de datos
-- financieros, que no están en esta tabla.
create policy "perfiles: el super ve todos"
    on public.perfiles for select
    to authenticated
    using ((select public.es_superusuario()));

-- La fila propia, y por el grant de arriba solo la columna
-- debe_cambiar_password. Las dos mitades juntas: la policy limita la FILA, el
-- grant limita la COLUMNA. Con una sola de las dos, esto sería un agujero.
create policy "perfiles: editar el propio"
    on public.perfiles for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

-- No hay policy de INSERT ni de DELETE: los perfiles los crea el trigger y los
-- borra el cascade de auth.users. Lo que no está permitido, está prohibido.


-- --------------------------------------------- administración de estados ---
--
-- El superusuario no puede hacer UPDATE de `estado` directo: se lo impide el
-- grant de columna, que es por rol de Postgres (`authenticated`) y no por
-- usuario. Pasa por esta función, que es el único camino y por eso el único
-- lugar donde hay que revisar el permiso.
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

    -- Pausarse a uno mismo deja el sistema sin ningún superusuario activo y sin
    -- forma de volver desde la web: habría que entrar por el SQL Editor.
    if p_user_id = auth.uid() then
        raise exception 'No podés cambiar tu propio estado.';
    end if;

    update public.perfiles set estado = p_estado where user_id = p_user_id;
end;
$$;

revoke execute on function public.admin_cambiar_estado(uuid, text) from public, anon;
grant  execute on function public.admin_cambiar_estado(uuid, text) to authenticated;

-- El `rol` a propósito NO tiene función de administración: se cambia a mano
-- desde el SQL Editor. Es la operación que crea más superusuarios, o sea la que
-- más rinde comprometer, y no se usa nunca en la vida normal del sistema.


-- =========================================================================
-- PASO 1 - usuarios_telegram
-- =========================================================================
--
-- El bot recibe un chat_id y necesita saber de quién es el gasto. Hoy eso sale
-- de SUPABASE_USER_ID en el .env, que es una constante: un solo dueño.
--
-- chat_id es la PK y no user_id: la pregunta que se hace siempre es "este
-- chat, ¿de quién es?", y la PK garantiza que tenga UNA sola respuesta. Al
-- revés admite varias (mismo usuario, varios chats), que no molesta.

create table if not exists public.usuarios_telegram (
    chat_id    bigint      primary key,

    user_id    uuid        not null
                           references auth.users (id) on delete cascade,

    -- Para reconocer la fila de un vistazo en el panel de Supabase.
    alias      text        check (alias is null or char_length(alias) between 1 and 60),

    creado_en  timestamptz not null default now()
);

create index if not exists usuarios_telegram_user_idx
    on public.usuarios_telegram (user_id);

-- Segunda FK, contra `perfiles`. No es redundante con la de auth.users: esta
-- es la que impide vincular un chat a un usuario que no tiene perfil, que es
-- un estado en el que el bot no sabría si la cuenta está activa y por las
-- dudas no atendería a nadie.
--
-- En un bloque porque `add constraint` no admite "if not exists" y este archivo
-- se puede volver a correr.
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

-- Solo lectura de lo propio, para que la web pueda mostrar "tu Telegram está
-- vinculado". No hay INSERT/UPDATE/DELETE para nadie: si el navegador pudiera
-- escribir acá, cualquiera se apuntaría el chat_id de otro y el bot le
-- mandaría los movimientos ajenos. Vincular es tarea del bot, con service_role,
-- después de verificar un código.
create policy "telegram: ver los propios"
    on public.usuarios_telegram for select
    to authenticated
    using ((select auth.uid()) = user_id);


-- ------------------------------------------------------ VINCULAR UN CHAT ---
--
-- Dos datos y listo: el chat_id de Telegram y el email de la cuenta.
--
-- CÓMO CONSEGUIR EL chat_id
-- Que la persona le escriba cualquier cosa al bot. Como todavía no está
-- vinculada, le va a contestar "No tengo tu acceso habilitado" y abajo su
-- número de chat: ese es. (También sale en el log del servidor, o
-- preguntándole a @userinfobot en Telegram.)
--
-- No es un secreto: es el número del propio chat de esa persona, y con él solo
-- no se puede hacer nada. Escribir en esta tabla necesita el SQL Editor o la
-- service_role; desde el navegador no hay policy de insert.
--
-- Correr esto, cambiando los dos valores:
/*
insert into public.usuarios_telegram (chat_id, user_id, alias)
select 123456789,                          -- <<< el chat_id
       u.id,
       'Nombre para reconocerla'
from auth.users u
where lower(u.email) = lower('persona@ejemplo.com')   -- <<< el email
on conflict (chat_id) do update
    set user_id = excluded.user_id,
        alias   = excluded.alias;
*/
--
-- El `on conflict` hace que revincular un chat a otra cuenta sea correr lo
-- mismo de nuevo, en vez de un delete y un insert.
--
-- Si el insert no afecta ninguna fila, el email no existe en auth.users. Si
-- falla por `usuarios_telegram_perfil_fk`, existe pero no tiene perfil.
--
-- Y ACORDARSE DEL ESTADO: el trigger del PASO 0 crea los perfiles en
-- 'pendiente', que no habilita nada. Vincular no alcanza; hay que activar:
/*
update public.perfiles set estado = 'activo'
where lower(email) = lower('persona@ejemplo.com');
*/
--
-- Para ver cómo quedó todo:
/*
select p.email, p.estado, p.rol, t.chat_id, t.alias
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;
*/


-- =========================================================================
-- PASO 2 - movimientos.user_id
-- =========================================================================
--
-- Va en tres tiempos y no en uno solo, por dos razones:
--
--   a) `add column ... not null` sobre una tabla con filas falla, porque las
--      que ya están quedarían en null.
--   b) `add column ... default auth.uid()` tampoco sirve: auth.uid() es STABLE,
--      así que Postgres la evalúa UNA vez al momento del ALTER y guarda ese
--      resultado para todas las filas viejas. Corriendo desde el SQL Editor
--      auth.uid() es NULL, o sea que el default no rellenaría nada.
--
-- Entonces: primero la columna vacía, después el UPDATE explícito, y recién
-- ahí el NOT NULL y el default para las filas nuevas.

-- (a) La columna, todavía nullable y sin default.
alter table public.movimientos
    add column if not exists user_id uuid references auth.users (id) on delete cascade;


-- (b) El relleno. Todo lo que ya existe pasa a ser tuyo.
do $$
declare
    -- >>>>>>>>>>>>>>>>>>>>>>> CAMBIAR ACÁ SI NO ES ESTE <<<<<<<<<<<<<<<<<<<<<<
    mi_email  text := 'arealegalesastarsa@gmail.com';
    mi_id     uuid;
    n_mov     bigint;
    n_rec     bigint;
    n_ret     bigint;
begin
    select id into mi_id from auth.users where lower(email) = lower(mi_email);

    if mi_id is null then
        -- Aborta el script entero antes de tocar una sola fila.
        raise exception
            'No hay ningún usuario con el email %. Revisá Authentication -> Users.', mi_email;
    end if;

    -- Tu perfil: activo y superusuario. Si el trigger de arriba ya lo creó (o
    -- si esta migración se corre de nuevo), lo pisa. Sin este bloque te
    -- quedarías afuera de tu propia base: las policies del PASO 4 exigen perfil
    -- activo, y el default de la tabla es 'pendiente'.
    insert into public.perfiles (user_id, email, estado, rol, debe_cambiar_password)
    values (mi_id, mi_email, 'activo', 'superusuario', false)
    on conflict (user_id) do update
        set estado = 'activo',
            rol    = 'superusuario';

    update public.movimientos set user_id = mi_id where user_id is null;
    get diagnostics n_mov = row_count;

    -- Estas dos vienen con user_id nullable desde 005 y 007: las filas que
    -- cargó el bot con service_role pueden tener null, y una fila sin dueño no
    -- la puede leer nadie, porque ninguna policy la hace visible.
    update public.recordatorios set user_id = mi_id where user_id is null;
    get diagnostics n_rec = row_count;

    update public.retos set user_id = mi_id where user_id is null;
    get diagnostics n_ret = row_count;

    raise notice 'Asignado a % (%): % movimientos, % recordatorios, % retos.',
        mi_email, mi_id, n_mov, n_rec, n_ret;
end $$;


-- (c) Recién ahora se puede exigir. El default queda por consistencia con
-- objetivos e inversiones: se completa solo cuando el INSERT viaja con el JWT
-- de un usuario logueado. Cuando escribe el bot (service_role) auth.uid() es
-- NULL, y entonces el not null hace que el insert FALLE en vez de crear una
-- fila huérfana. Eso es lo buscado: un error ruidoso, no una fila invisible.
alter table public.movimientos
    alter column user_id set default auth.uid();

alter table public.movimientos
    alter column user_id set not null;


-- Índices: a partir de ahora TODA consulta lleva user_id = ... adelante, sea
-- por RLS o por el filtro del bot. Los índices viejos empiezan por fecha, así
-- que con dos usuarios ya dejan de servir para acotar.
create index if not exists movimientos_user_fecha_idx
    on public.movimientos (user_id, fecha desc, id desc);

create index if not exists movimientos_user_tipo_fecha_idx
    on public.movimientos (user_id, tipo, fecha desc);

-- Los de schema.sql (movimientos_fecha_idx, movimientos_tipo_fecha_idx) quedan
-- redundantes, pero borrarlos es una decisión aparte y reversible. Cuando
-- confirmes que las consultas usan los nuevos:
--   drop index if exists public.movimientos_fecha_idx;
--   drop index if exists public.movimientos_tipo_fecha_idx;


-- ----------------------------------------- objetivo_id de otro usuario -----
--
-- `movimientos.objetivo_id` apunta a objetivos, y la FK sola no mira de quién
-- es el objetivo. Con las policies de escritura del PASO 4, alguien podría
-- insertar un movimiento propio apuntando al objetivo de otro: RLS lo aprueba,
-- porque la fila que se escribe es suya.
--
-- No filtra datos (el otro nunca ve ese movimiento), pero le ensucia el
-- progreso del objetivo desde afuera. El trigger cierra esa puerta, y como
-- corre en el motor también aplica al bot, que saltea RLS.
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


-- =========================================================================
-- PASO 3 - cerrar las huérfanas de recordatorios y retos
-- =========================================================================
--
-- El UPDATE ya se hizo en el DO del PASO 2. Acá solo se exige que no vuelvan a
-- aparecer. Mismo motivo que en movimientos: una fila con user_id null no es de
-- nadie, no la lee ninguna policy y no hay forma de reclamarla desde la app.

alter table public.recordatorios alter column user_id set not null;
alter table public.retos         alter column user_id set not null;


-- =========================================================================
-- PASO 4 - RLS estricto
-- =========================================================================
--
-- Las cuatro operaciones, en las tres tablas. El patrón es siempre el mismo:
--
--   USING      -> qué filas EXISTENTES ve la operación. Va en SELECT, UPDATE,
--                 DELETE. Una fila que no pasa el USING no es que dé error:
--                 es que no existe para vos.
--   WITH CHECK -> cómo queda la fila DESPUÉS de escribir. Va en INSERT y
--                 UPDATE. Es lo que impide crear o dejar una fila a nombre de
--                 otro.
--
-- UPDATE lleva las dos, y omitir el WITH CHECK es el error clásico: sin él
-- podés editar tu propia fila y en el mismo UPDATE cambiarle el user_id a
-- otra persona. RLS lo aprobaría, porque mira la fila de entrada.
--
-- `to authenticated` excluye a `anon`: sin sesión, auth.uid() es NULL y ningún
-- `= user_id` da true, pero decirlo explícito ahorra depender de eso.
--
-- El `(select ...)` alrededor de auth.uid() y de es_activo() no es cosmético:
-- así Postgres las evalúa una sola vez por consulta (InitPlan) en vez de una
-- vez por fila.
--
-- ------------------------------------------------------------------------
-- NOTA SOBRE LAS POLICIES DE ESCRITURA
--
-- Hoy la web NO escribe movimientos ni inversiones: los carga el bot. Estas
-- policies habilitan algo que hoy no está habilitado. Es lo que pediste
-- (SELECT/INSERT/UPDATE/DELETE en las tres) y es correcto si la web va a
-- editar; si preferís seguir con la web de solo lectura, la superficie más
-- chica es dejar únicamente las de SELECT y borrar las otras tres de
-- movimientos y de inversiones. Aislamiento no cambia; permiso sí.
-- ------------------------------------------------------------------------


-- ---------------------------------------------------------- movimientos ----
alter table public.movimientos enable row level security;

-- La vieja: `using (true)`, todos ven todo. Es exactamente el agujero que
-- avisaba el comentario de schema.sql. Se va.
--
-- OJO CON ESTE `drop policy if exists`: borra POR NOMBRE, y solo por el nombre
-- que está escrito acá. Si en la base la policy vieja se llama de otra forma
-- —creada a mano, o con una versión anterior de schema.sql—, esto no encuentra
-- nada, no avisa, y la permisiva sobrevive al lado de las nuevas. Como las
-- policies permisivas se combinan con OR, una sola `using (true)` que quede
-- vuelve inútiles a las otras cuatro.
--
-- Pasó de verdad. El arreglo, que busca por lo que las policies HACEN en vez de
-- por cómo se llaman, está en migrations/012_barrer_policies_permisivas.sql.
-- Correr esa después de esta, siempre.
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


-- ------------------------------------------------------------ objetivos ----
-- Ya tenía las cuatro desde schema.sql. Se rehacen para sumarles es_activo():
-- sin eso, un usuario pausado seguiría creando y editando objetivos.
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


-- ----------------------------------------------------------- inversiones ---
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


-- ------------------------------------------- las otras tablas con dueño ----
-- alertas, recordatorios, retos y narrativas ya tienen policies de SELECT
-- filtradas por auth.uid() (migraciones 004, 005 y 007), y no tienen policies
-- de escritura, así que desde el navegador ya son de solo lectura y solo lo
-- propio. Quedan como están: agregarles escritura sería ampliar permisos, no
-- cerrar un agujero.
--
-- `rendimientos_billeteras` (008) no tiene dueño y está bien: una TNA es
-- pública, igual para todos. No hay nada que aislar ahí.


-- =========================================================================
-- PASO 5 - verificación
-- =========================================================================

-- (1) Que no queden filas sin dueño. Las tres tienen que dar 0.
select 'movimientos'   as tabla, count(*) as sin_dueno from public.movimientos   where user_id is null
union all
select 'objetivos',    count(*) from public.objetivos    where user_id is null
union all
select 'inversiones',  count(*) from public.inversiones  where user_id is null;

-- (2) Que no haya ninguna tabla de datos con RLS apagado. Tiene que dar vacío.
select relname as tabla_sin_rls
from pg_class
where relnamespace = 'public'::regnamespace
  and relkind = 'r'
  and not relrowsecurity;

-- (3) Las policies, tabla por tabla. Ninguna de las tres tablas de datos puede
-- tener un `qual` que diga solo `true`.
select tablename, policyname, cmd, roles, qual, with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('movimientos', 'objetivos', 'inversiones',
                    'perfiles', 'usuarios_telegram')
order by tablename, cmd;


-- ------------------------------------------------- SIMULACRO DE INTRUSIÓN --
--
-- Lo anterior verifica que las policies existan. Esto verifica que FUNCIONEN,
-- que es otra cosa. Se hace pasar por un usuario cualquiera —lo mismo que
-- lograría alguien que edite el JavaScript o que mande el request con curl— y
-- cuenta lo que ve.
--
-- Todo adentro de un begin/rollback: no escribe nada.
--
-- Reemplazá el uuid por el de OTRO usuario (Authentication -> Users). Las tres
-- cuentas tienen que dar 0. Si alguna da distinto de 0, hay un agujero.

/*
begin;
    set local role authenticated;
    set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000000","role":"authenticated"}';

    select count(*) as movimientos_ajenos from public.movimientos;
    select count(*) as objetivos_ajenos   from public.objetivos;
    select count(*) as inversiones_ajenas from public.inversiones;

    -- Y esto tiene que dar error de permisos, no éxito: es el intento de
    -- autoascenderse a superusuario editando el perfil propio.
    -- update public.perfiles set rol = 'superusuario' where user_id = auth.uid();
rollback;
*/


-- =========================================================================
-- EL CÓDIGO: QUÉ YA ESTÁ Y QUÉ FALTA
-- =========================================================================
--
-- RLS protege el camino del navegador. El bot usa service_role, que saltea RLS
-- por diseño: ahí el aislamiento es responsabilidad del código Python.
--
-- YA HECHO (el bot es multiusuario y no arranca sin estas tablas):
--
--   app/usuarios.py   nuevo. Resuelve chat_id -> user_id contra
--                     usuarios_telegram + perfiles, con caché de 60s. Falla
--                     cerrada: ante cualquier duda devuelve None y el mensaje
--                     no se procesa.
--   app/db.py         las 27 funciones que tocan datos de alguien exigen
--                     user_id como parámetro obligatorio de solo palabra
--                     clave. SUPABASE_USER_ID no se usa más.
--   app/main.py       el chat se autoriza ANTES de mirar el contenido del
--                     mensaje; el user_id viaja por todo el flujo.
--   app/config.py     CHATS_PERMITIDOS pasó a ser un cerrojo opcional.
--
-- ORDEN DE DESPLIEGUE: primero este SQL, después el código. Al revés, el bot
-- consulta dos tablas que no existen y no atiende a nadie.
--
-- FALTA (fuera del alcance de esta migración):
--
--   1. web/js/auth.js: después del login, leer el perfil propio. Si
--      debe_cambiar_password es true, mandar a cambiarla. Si estado no es
--      'activo', mostrar el motivo en vez de un dashboard en cero.
--
--   2. Los crons de .github/workflows: los que escriben datos por usuario
--      (narrativas, retos) tienen que iterar sobre los perfiles activos en vez
--      de asumir uno solo. Los de alertas y recordatorios ya andan: recorren
--      todas las filas y cada aviso sale al chat_id de la suya. El de
--      rendimientos tampoco necesita cambios, que es dato público sin dueño.
--
--   3. Vinculación autoservicio, si algún día molesta hacerla a mano: la web
--      genera un código con el usuario logueado, la persona manda /vincular
--      <código> al bot y el bot inserta con service_role. Nunca desde el
--      navegador: la tabla no tiene policy de insert justamente para eso.
