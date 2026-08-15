-- Narrativa mensual, retos de ahorro y foto en los objetivos.
--
-- Correr en: Supabase -> SQL Editor -> New query -> Run.
-- Es idempotente: se puede volver a correr sin romper nada.

-- ==================================================== NARRATIVA MENSUAL ===
-- El resumen en prosa de cada mes cerrado. Se guarda para poder releer meses
-- anteriores sin volver a gastar una llamada a Gemini: el mes ya pasó, así que
-- el texto no va a cambiar.
create table if not exists public.narrativas (
    id         uuid        primary key default gen_random_uuid(),
    user_id    uuid        not null default auth.uid()
                           references auth.users (id) on delete cascade,
    -- "2026-08". Uno por usuario y por mes: la unicidad la garantiza el índice
    -- de abajo, no un chequeo en el código.
    mes        text        not null check (mes ~ '^\d{4}-\d{2}$'),
    texto      text        not null check (char_length(texto) between 1 and 4000),
    moneda     text        not null default 'ARS',
    created_at timestamptz not null default now()
);

create unique index if not exists narrativas_usuario_mes_idx
    on public.narrativas (user_id, mes);

alter table public.narrativas enable row level security;

drop policy if exists "narrativas: leer las propias" on public.narrativas;
drop policy if exists "narrativas: crear las propias" on public.narrativas;

create policy "narrativas: leer las propias"
    on public.narrativas for select to authenticated
    using (auth.uid() = user_id);

-- La web SÍ escribe acá, a diferencia de casi todo lo demás: genera el texto
-- con el backend y lo guarda. El with check ata la fila al usuario logueado,
-- así que no puede escribir narrativas ajenas aunque edite el JavaScript.
create policy "narrativas: crear las propias"
    on public.narrativas for insert to authenticated
    with check (auth.uid() = user_id);

-- ======================================================= RETOS DE AHORRO ==
create table if not exists public.retos (
    id            uuid        primary key default gen_random_uuid(),
    user_id       uuid        references auth.users (id) on delete cascade,
    -- El chat que lo aceptó. Como en `recordatorios`, la identidad del bot y
    -- la de la web son distintas y el bot tiene que poder escribir sin sesión.
    chat_id       bigint,

    -- Qué se propone evitar o limitar. Sale de las categorías del usuario.
    categoria     text        not null check (char_length(categoria) between 1 and 60),
    -- "sin_gastos" = no gastar nada del rubro. "tope" = no pasar de `objetivo`.
    tipo          text        not null default 'sin_gastos'
                              check (tipo in ('sin_gastos', 'tope')),
    -- Para el tipo "tope": cuánto es el máximo. Null en "sin_gastos".
    objetivo      numeric(14,2) check (objetivo is null or objetivo > 0),
    -- Lo que se estima ahorrar si se cumple. Es una ESTIMACIÓN basada en el
    -- historial, y así se dice en pantalla.
    ahorro_estimado numeric(14,2) not null check (ahorro_estimado >= 0),
    moneda        text        not null default 'ARS',

    desde         date        not null,
    hasta         date        not null,
    check (hasta >= desde),

    -- activo -> cumplido | fallido | abandonado. Un reto vencido lo cierra el
    -- código al revisarlo, no un trigger: así el cierre queda en un solo lugar.
    estado        text        not null default 'activo'
                              check (estado in ('activo', 'cumplido', 'fallido', 'abandonado')),
    cerrado_en    timestamptz,
    -- Cuánto se gastó realmente del rubro durante el reto. Se completa al cerrar.
    gastado       numeric(14,2),

    created_at    timestamptz not null default now()
);

-- El bot pide "los activos de este chat" en cada mensaje que registra un gasto.
create index if not exists retos_activos_idx
    on public.retos (chat_id, estado) where estado = 'activo';
create index if not exists retos_usuario_idx on public.retos (user_id, created_at desc);

alter table public.retos enable row level security;

drop policy if exists "retos: leer los propios" on public.retos;

-- Solo lectura desde la web: los retos los propone y cierra el bot, que
-- escribe con service_role. La web los muestra.
create policy "retos: leer los propios"
    on public.retos for select to authenticated
    using (auth.uid() = user_id);

-- ==================================================== FOTO EN OBJETIVOS ===
alter table public.objetivos
    -- La RUTA dentro del bucket, no la URL. La URL firmada se pide al mostrar
    -- y vence; guardarla dejaría links rotos en la base.
    add column if not exists foto_path text;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.objetivos'::regclass
          and conname = 'objetivos_foto_path_check'
    ) then
        alter table public.objetivos
            add constraint objetivos_foto_path_check
            check (foto_path is null or char_length(foto_path) between 1 and 300);
    end if;
end $$;

-- ------------------------------------------------ Bucket de Storage -------
-- Privado, no público: son fotos de cosas que la persona quiere comprar, y un
-- bucket público las deja accesibles a cualquiera que adivine la URL.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'objetivos', 'objetivos', false, 5242880,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
on conflict (id) do update
set public = false,
    file_size_limit = 5242880,
    allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp', 'image/gif'];

drop policy if exists "objetivos: ver mis fotos" on storage.objects;
drop policy if exists "objetivos: subir mis fotos" on storage.objects;
drop policy if exists "objetivos: borrar mis fotos" on storage.objects;

-- Cada usuario vive en una carpeta con su uuid: objetivos/<user_id>/<archivo>.
-- storage.foldername() devuelve el path partido, y su primer elemento tiene
-- que ser el uuid de quien pide. Sin esto, cualquiera con sesión podría leer
-- las fotos de todos.
create policy "objetivos: ver mis fotos"
    on storage.objects for select to authenticated
    using (
        bucket_id = 'objetivos'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "objetivos: subir mis fotos"
    on storage.objects for insert to authenticated
    with check (
        bucket_id = 'objetivos'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "objetivos: borrar mis fotos"
    on storage.objects for delete to authenticated
    using (
        bucket_id = 'objetivos'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- Verificación.
select 'tablas' as que, table_name as detalle
from information_schema.tables
where table_schema = 'public' and table_name in ('narrativas', 'retos')
union all
select 'columna foto_path', column_name
from information_schema.columns
where table_schema = 'public' and table_name = 'objetivos' and column_name = 'foto_path'
union all
select 'bucket', id from storage.buckets where id = 'objetivos'
union all
select 'policies storage', policyname
from pg_policies where schemaname = 'storage' and policyname like 'objetivos:%';
