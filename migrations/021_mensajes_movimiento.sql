-- De que movimiento habla cada mensaje de confirmacion del bot.
--
-- EL PROBLEMA
-- El bot contesta "Gasto de $8.500 en supermercado registrado" y ahi se acaba
-- la historia: si el monto estaba mal, no habia forma de corregirlo desde el
-- chat. Telegram permite responder a un mensaje y avisa a que message_id se
-- respondio, pero eso solo sirve si alguien anoto que ese mensaje era ESE
-- movimiento.
--
-- POR QUE UNA TABLA Y NO MEMORIA DEL PROCESO
-- Render duerme el servicio tras ~15 minutos sin trafico (ver la memoria de
-- deploy): un diccionario en RAM se vacia solo, y justo el caso comun es
-- corregir un gasto horas despues, no en el mismo minuto. En memoria la
-- respuesta seria "no se de que movimiento me hablas" casi siempre.
--
-- QUE ES Y QUE NO ES
-- Es un indice de conveniencia entre Telegram y la base. NO es parte del
-- historial: si se pierde una fila, el movimiento sigue intacto y lo unico que
-- pasa es que ese mensaje viejo deja de ser editable por reply. Por eso no le
-- cuelga nada mas y el on delete cascade puede llevarsela sin pensarlo.
--
-- Idempotente: se puede volver a correr sin romper nada.


create table if not exists public.mensajes_movimiento (
    -- El chat y el mensaje del BOT al que el usuario le responde. Juntos son la
    -- clave: Telegram numera los message_id por chat, no globalmente, asi que
    -- el message_id solo no identifica nada.
    chat_id       bigint      not null,
    message_id    bigint      not null,

    -- Si el movimiento se borra, la referencia se va con el. Un reply a un
    -- mensaje cuyo movimiento ya no existe tiene que contestar "esto ya no
    -- esta", no apuntar a un id fantasma.
    movimiento_id bigint      not null
                              references public.movimientos (id) on delete cascade,

    -- Redundante con movimientos.user_id, y a proposito: permite chequear que
    -- quien responde es el dueño sin tener que leer el movimiento primero.
    user_id       uuid        not null
                              references auth.users (id) on delete cascade,

    creado_en     timestamptz not null default now(),

    primary key (chat_id, message_id)
);


-- Postgres NO crea indice para la tabla que referencia: sin esto, cada borrado
-- de un movimiento escanea la tabla entera para resolver el cascade.
create index if not exists mensajes_movimiento_mov_idx
    on public.mensajes_movimiento (movimiento_id);

-- Para poder barrer las viejas algun dia sin escanear todo.
create index if not exists mensajes_movimiento_creado_idx
    on public.mensajes_movimiento (creado_en);


-- ---------------------------------------------------------------------------
-- RLS
--
-- Esta tabla la escribe y la lee SOLO el bot, con service_role, que saltea RLS
-- por diseño. La web no la necesita: no muestra mensajes de Telegram.
--
-- Por eso, a diferencia de categorias, aca no se escriben policies "por si
-- acaso". RLS queda prendida y sin ninguna policy, que en Postgres significa
-- que nadie que pase por RLS ve una sola fila. Sumado a revocar los grants,
-- son dos cerrojos independientes sobre la clave anon, que esta a la vista en
-- la web.
-- ---------------------------------------------------------------------------

alter table public.mensajes_movimiento enable row level security;

revoke all on public.mensajes_movimiento from anon, authenticated;


-- ---------------------------------------------------------------------------
-- Comprobaciones. No modifican nada.
-- ---------------------------------------------------------------------------

-- La tabla existe y esta vacia (o con lo que haya juntado). TIENE que decir
-- rowsecurity = true.
select relname, relrowsecurity as rls_prendida
from pg_class
where relname = 'mensajes_movimiento';

-- Cuantas policies tiene. TIENE QUE DAR CERO: sin policies y con RLS prendida,
-- la clave anon no puede leer ni una fila aunque alguien le diera el grant.
select count(*) as policies_que_no_deberian_existir
from pg_policies
where schemaname = 'public' and tablename = 'mensajes_movimiento';
