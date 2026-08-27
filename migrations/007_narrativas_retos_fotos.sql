-- Narrativa mensual, retos de ahorro y foto en los objetivos.

create table if not exists public.narrativas (
    id         uuid        primary key default gen_random_uuid(),
    user_id    uuid        not null default auth.uid()
                           references auth.users (id) on delete cascade,
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

create policy "narrativas: crear las propias"
    on public.narrativas for insert to authenticated
    with check (auth.uid() = user_id);

create table if not exists public.retos (
    id            uuid        primary key default gen_random_uuid(),
    user_id       uuid        references auth.users (id) on delete cascade,
    chat_id       bigint,

    categoria     text        not null check (char_length(categoria) between 1 and 60),
    tipo          text        not null default 'sin_gastos'
                              check (tipo in ('sin_gastos', 'tope')),
    objetivo      numeric(14,2) check (objetivo is null or objetivo > 0),
    ahorro_estimado numeric(14,2) not null check (ahorro_estimado >= 0),
    moneda        text        not null default 'ARS',

    desde         date        not null,
    hasta         date        not null,
    check (hasta >= desde),

    estado        text        not null default 'activo'
                              check (estado in ('activo', 'cumplido', 'fallido', 'abandonado')),
    cerrado_en    timestamptz,
    gastado       numeric(14,2),

    created_at    timestamptz not null default now()
);

create index if not exists retos_activos_idx
    on public.retos (chat_id, estado) where estado = 'activo';
create index if not exists retos_usuario_idx on public.retos (user_id, created_at desc);

alter table public.retos enable row level security;

drop policy if exists "retos: leer los propios" on public.retos;

create policy "retos: leer los propios"
    on public.retos for select to authenticated
    using (auth.uid() = user_id);

alter table public.objetivos
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
