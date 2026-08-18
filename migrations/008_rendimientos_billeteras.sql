-- Comparador de rendimientos de billeteras virtuales.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.
--
-- ------------------------------------------------- POR QUÉ NO HAY user_id ---
--
-- Es la primera tabla del proyecto sin dueño, y es a propósito: una TNA es un
-- dato público, igual para todos. `movimientos`, `objetivos` y `alertas` son
-- del usuario y por eso llevan user_id y RLS por fila; acá guardar la misma
-- tabla replicada por usuario sería copiar 26 filas idénticas por cada cuenta
-- y tener que actualizarlas todas en cada corrida del cron.
--
-- La consecuencia está en las policies: se puede LEER estando logueado, y no
-- hay policy de escritura. Quien escribe es el cron, con service_role, que
-- saltea RLS. Igual que en `alertas`: lo que no está permitido, está prohibido.
--
-- ------------------------------------------- LAS DOS FECHAS, Y POR QUÉ DOS ---
--
-- `fecha_actualizacion` es de CUÁNDO ES EL DATO (la fecha que publica la
-- fuente). `sincronizado_en` es cuándo lo trajimos nosotros.
--
-- No son lo mismo y confundirlas es justamente el modo de fallar silencioso que
-- hay que evitar: si el scraper se rompe el 10 y sigue corriendo, la segunda se
-- actualiza todos los días y la pantalla diría "actualizado hace 2 minutos"
-- mostrando tasas de hace tres semanas. La que se muestra en pantalla es la
-- primera.

create table if not exists public.rendimientos_billeteras (
    id                  uuid          primary key default gen_random_uuid(),

    -- Nombre de la billetera tal como la conoce el usuario ("Mercado Pago"),
    -- no el del fondo que hay atrás. Es la clave del upsert del cron: una
    -- billetera es una fila, y cada corrida la pisa en vez de apilar historial.
    nombre              text          not null unique
                                      check (char_length(nombre) between 1 and 60),

    -- 'fci': la billetera invierte el saldo en un fondo común de dinero y el
    --        rendimiento es variable y no garantizado.
    -- 'cuenta_remunerada': la entidad paga una tasa que ella misma declara.
    -- La distinción no es cosmética: cambia qué tan firme es el número y si
    -- puede haber tope de monto, así que la pantalla las muestra separadas.
    tipo                text          not null
                                      check (tipo in ('fci', 'cuenta_remunerada')),

    -- TNA en PORCENTAJE, no en fracción: 17.98 es 17,98% anual.
    --
    -- Se eligió porcentaje —y no la fracción que usa la API de plazo fijo—
    -- porque es lo que se muestra y lo que el usuario compara. numeric(7,4)
    -- llega hasta 999,9999%, de sobra para cualquier tasa argentina.
    tna                 numeric(7,4)  not null check (tna >= 0 and tna < 1000),

    -- Hasta qué saldo se paga esa TNA. NULL = sin tope conocido, que NO es lo
    -- mismo que sin tope: de los fondos comunes no hay tope, pero de varias
    -- cuentas remuneradas simplemente no publicamos el dato. El simulador de la
    -- web avisa la diferencia en vez de asumir que no hay límite.
    tope_monto          numeric(14,2) check (tope_monto is null or tope_monto > 0),

    -- De cuándo es la tasa, según la fuente. Es la que se muestra en pantalla.
    fecha_actualizacion date          not null,

    -- Qué fondo hay atrás, cuando el rendimiento sale de uno. Se guarda para
    -- que el número sea auditable: sin esto, un "Mercado Pago 17,98%" no se
    -- puede verificar contra ningún lado.
    fondo               text,

    -- De dónde salió la fila, para poder distinguir de un vistazo qué se está
    -- sirviendo si una de las dos fuentes se cae y la otra no.
    fuente              text          not null default 'argentinadatos',

    -- Cuándo la escribió el cron. Ver la nota de arriba: NO es la fecha del
    -- dato, y por eso no es la que se muestra.
    sincronizado_en     timestamptz   not null default now()
);

-- La pantalla pide "todas, de mayor a menor TNA". Con 30 filas da igual, pero
-- el índice cuesta nada y evita tener que acordarse cuando sean 200.
create index if not exists rendimientos_billeteras_tna_idx
    on public.rendimientos_billeteras (tna desc);

-- ------------------------------------------------------------------ RLS ----
alter table public.rendimientos_billeteras enable row level security;

drop policy if exists "rendimientos: leer" on public.rendimientos_billeteras;

-- Solo SELECT, y solo logueado. No hay policy de INSERT/UPDATE/DELETE: escribe
-- únicamente el cron con service_role.
create policy "rendimientos: leer"
    on public.rendimientos_billeteras for select
    to authenticated
    using (true);

-- Verificación: una sola policy, de select, para authenticated.
select policyname, cmd, roles
from pg_policies
where schemaname = 'public' and tablename = 'rendimientos_billeteras';
