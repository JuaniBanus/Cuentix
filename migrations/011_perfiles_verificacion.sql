-- ¿El alta automática de perfiles funciona? Verificación y red de contención.
--
-- Correr en: Supabase -> SQL Editor. No cambia el esquema: solo verifica y,
-- si hace falta, rellena. Se puede correr las veces que quieras.
--
-- ESTE ARCHIVO SE CORRE POR PARTES, NO ENTERO.
-- El PASO 2 termina en un `rollback` a proposito. El SQL Editor mete todo lo
-- que le mandes en una sola transaccion, asi que corriendo el archivo completo
-- ese rollback se llevaria puesto tambien al PASO 3. Seleccionas un paso, Run,
-- mirás el resultado, y recien ahi el siguiente.
--
-- =========================================================================
-- POR QUÉ UN USUARIO VIEJO PUEDE NO TENER PERFIL
-- =========================================================================
--
-- No es una falla del trigger: los triggers no corren para atrás. `perfiles_alta`
-- dispara en INSERT OR UPDATE OF email sobre auth.users, así que una cuenta que
-- YA EXISTÍA cuando se creó el trigger nunca generó ningún evento.
--
-- Para esas cuentas viejas estaba el DO del PASO 2 de la 009, que creaba el
-- perfil del email hardcodeado. Solo cubría a ese, y solo si la cuenta existía
-- en auth.users cuando se corrió: si se creó después, el bloque abortó entero.
--
-- El PASO 3 de acá abajo cierra ese agujero para cualquier cuenta, sin importar
-- cuándo se creó.
--
-- Y ojo con la conclusión fácil: que el trigger ande NO significa que un usuario
-- nuevo pueda usar la app. Nace en 'pendiente', que no habilita nada. Falta
-- activarlo a mano. Eso es a propósito —una cuenta nueva no se habilita sola—,
-- pero es lo que más confunde cuando alguien no puede entrar.


-- =========================================================================
-- PASO 1 - ¿está instalado y habilitado?
-- =========================================================================
--
-- Tiene que devolver UNA fila: perfiles_alta, habilitado. Si devuelve vacío, el
-- create trigger de la 009 no llegó a correr o falló, y hay que volver a
-- correr esa sección.
--
-- El estado importa tanto como la existencia: un trigger deshabilitado sigue
-- apareciendo en el catálogo y no hace absolutamente nada.

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

-- Y que la función que llama exista y siga siendo security definer: sin eso,
-- corre con los permisos de quien se registra, que no puede escribir perfiles.
select p.proname as funcion,
       p.prosecdef as es_security_definer,
       p.proconfig as search_path
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname = 'perfil_para_usuario_nuevo';


-- =========================================================================
-- PASO 2 - probarlo de verdad, sin dejar rastro
-- =========================================================================
--
-- Que el trigger exista no prueba que funcione. Esto crea un usuario, mira si
-- apareció el perfil y deshace todo.
--
-- El rollback no es opcional ni decorativo: sin él queda un usuario de mentira
-- en auth.users. Correr el bloque ENTERO, de begin a rollback, de una sola vez.
--
-- Si el insert se queja de alguna columna NOT NULL —la forma de auth.users
-- cambia entre versiones de Supabase—, agregala y volvé a correr: como termina
-- en rollback, reintentar no cuesta nada.

begin;

    insert into auth.users (id, email)
    values (gen_random_uuid(), 'prueba-trigger@ejemplo.com');

    -- TIENE QUE devolver una fila:
    --   estado = 'pendiente', rol = 'usuario', debe_cambiar_password = true
    -- Vacío = el trigger no disparó.
    select user_id, email, estado, rol, debe_cambiar_password, creado_en
    from public.perfiles
    where email = 'prueba-trigger@ejemplo.com';

rollback;

-- Comprobación de que el rollback hizo lo suyo. Las dos tienen que dar 0.
select
    (select count(*) from auth.users       where email = 'prueba-trigger@ejemplo.com') as usuario_quedo,
    (select count(*) from public.perfiles  where email = 'prueba-trigger@ejemplo.com') as perfil_quedo;


-- =========================================================================
-- PASO 3 - red de contención: cualquier usuario sin perfil
-- =========================================================================
--
-- Primero mirar quiénes son. Vacío = está todo bien y no hace falta el insert.

select u.id, u.email, u.created_at
from auth.users u
left join public.perfiles p on p.user_id = u.id
where p.user_id is null
order by u.created_at;

-- Y crearles el perfil. Nacen en 'pendiente', igual que los del trigger: esto
-- repara la falta de perfil, no habilita a nadie.
insert into public.perfiles (user_id, email)
select u.id, u.email
from auth.users u
left join public.perfiles p on p.user_id = u.id
where p.user_id is null
  and u.email is not null
on conflict (user_id) do nothing;


-- =========================================================================
-- PASO 4 - cómo quedó todo
-- =========================================================================

select p.email, p.estado, p.rol, p.debe_cambiar_password, t.chat_id
from public.perfiles p
left join public.usuarios_telegram t on t.user_id = p.user_id
order by p.creado_en;


-- =========================================================================
-- UN CASO EN EL QUE ESTE TRIGGER ROMPE EL ALTA
-- =========================================================================
--
-- `perfiles.email` es NOT NULL, y el trigger corre DESPUÉS del insert en
-- auth.users, dentro de la misma transacción. Si alguna vez llega un usuario
-- con email NULL, el insert en perfiles falla y se cae el alta ENTERA: la
-- persona no puede registrarse, y el error no dice nada de perfiles.
--
-- Hoy no puede pasar: el único login es email + contraseña. Pasaría si algún
-- día se prende login por teléfono, por OAuth sin email, o `signInAnonymously`.
-- Si eso llega, hay que decidir entre dos caminos —email nullable en perfiles,
-- o que el trigger saltee esos usuarios— y ninguno es gratis: el segundo
-- devuelve exactamente el problema que estas cuatro consultas arreglan.
--
-- El PASO 3 se puede volver a correr cuando quieras: es la forma barata de
-- enterarse de que alguien quedó sin perfil, sin esperar a que se queje.
