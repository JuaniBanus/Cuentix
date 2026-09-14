-- Unificar los sinonimos que dejo la epoca en que la IA inventaba categorias.
--
-- ESTA MIGRACION ES DESTRUCTIVA Y OPCIONAL. Reescribe movimientos.categoria,
-- asi que cambia la forma de los graficos: dos porciones chicas ("super" y
-- "supermercado") pasan a ser una sola. Eso es justamente el punto, pero es
-- irreversible sin un backup.
--
-- COMO SE CORRE
-- 1. Seleccionar con el mouse la PARTE 1 y apretar Run. Solo lee.
-- 2. Mirar el resultado: cada fila dice que etiqueta se convierte en cual y
--    cuantos movimientos toca. Si alguna regla no cierra, borrar esa linea del
--    mapa (aparece dos veces, en la PARTE 1 y en la PARTE 2: sacarla de las dos).
-- 3. Recien ahi seleccionar la PARTE 2 ENTERA -- del `do $unificar$` hasta el
--    `$unificar$;` -- y apretar Run. Es una sola sentencia: o entra todo o no
--    entra nada.
--
-- 019_categorias.sql tiene que estar corrida antes.


-- ===========================================================================
-- PARTE 1 - ENSAYO. No modifica nada.
-- ===========================================================================

with mapa(tipo, desde, hacia) as (values
    -- supermercado y afines
    ('gasto', 'super',            'supermercado'),
    ('gasto', 'súper',            'supermercado'),
    ('gasto', 'chino',            'supermercado'),
    ('gasto', 'almacen',          'supermercado'),
    ('gasto', 'almacén',          'supermercado'),
    ('gasto', 'verduleria',       'supermercado'),
    ('gasto', 'verdulería',       'supermercado'),
    ('gasto', 'carniceria',       'supermercado'),
    ('gasto', 'carnicería',       'supermercado'),
    ('gasto', 'panaderia',        'supermercado'),
    ('gasto', 'panadería',        'supermercado'),

    -- transporte
    ('gasto', 'taxi',             'transporte'),
    ('gasto', 'uber',             'transporte'),
    ('gasto', 'cabify',           'transporte'),
    ('gasto', 'remis',            'transporte'),
    ('gasto', 'colectivo',        'transporte'),
    ('gasto', 'bondi',            'transporte'),
    ('gasto', 'sube',             'transporte'),
    ('gasto', 'subte',            'transporte'),
    ('gasto', 'tren',             'transporte'),
    ('gasto', 'peaje',            'transporte'),
    ('gasto', 'estacionamiento',  'transporte'),

    -- nafta
    ('gasto', 'combustible',      'nafta'),
    ('gasto', 'ypf',              'nafta'),
    ('gasto', 'shell',            'nafta'),
    ('gasto', 'gnc',              'nafta'),
    ('gasto', 'gasoil',           'nafta'),

    -- servicios
    ('gasto', 'luz',              'servicios'),
    ('gasto', 'gas',              'servicios'),
    ('gasto', 'agua',             'servicios'),
    ('gasto', 'internet',         'servicios'),
    ('gasto', 'telefono',         'servicios'),
    ('gasto', 'teléfono',         'servicios'),
    ('gasto', 'celular',          'servicios'),
    ('gasto', 'cable',            'servicios'),
    ('gasto', 'edesur',           'servicios'),
    ('gasto', 'edenor',           'servicios'),
    ('gasto', 'metrogas',         'servicios'),

    -- comida
    ('gasto', 'resto',            'comida'),
    ('gasto', 'restaurante',      'comida'),
    ('gasto', 'delivery',         'comida'),
    ('gasto', 'almuerzo',         'comida'),
    ('gasto', 'cena',             'comida'),
    ('gasto', 'desayuno',         'comida'),
    ('gasto', 'cafe',             'comida'),
    ('gasto', 'café',             'comida'),
    ('gasto', 'bar',              'comida'),
    ('gasto', 'kiosco',           'comida'),
    ('gasto', 'heladeria',        'comida'),
    ('gasto', 'heladería',        'comida'),

    -- salud
    ('gasto', 'farmacia',         'salud'),
    ('gasto', 'medico',           'salud'),
    ('gasto', 'médico',           'salud'),
    ('gasto', 'dentista',         'salud'),
    ('gasto', 'obra social',      'salud'),
    ('gasto', 'prepaga',          'salud'),
    ('gasto', 'psicologa',        'salud'),
    ('gasto', 'psicóloga',        'salud'),
    ('gasto', 'psicologo',        'salud'),
    ('gasto', 'psicólogo',        'salud'),

    -- educacion
    ('gasto', 'educación',        'educacion'),
    ('gasto', 'colegio',          'educacion'),
    ('gasto', 'universidad',      'educacion'),
    ('gasto', 'curso',            'educacion'),
    ('gasto', 'libros',           'educacion'),

    -- impuestos
    ('gasto', 'monotributo',      'impuestos'),
    ('gasto', 'afip',             'impuestos'),
    ('gasto', 'arca',             'impuestos'),
    ('gasto', 'abl',              'impuestos'),
    ('gasto', 'patente',          'impuestos'),
    ('gasto', 'rentas',           'impuestos'),

    -- suscripciones
    ('gasto', 'netflix',          'suscripciones'),
    ('gasto', 'spotify',          'suscripciones'),
    ('gasto', 'disney',           'suscripciones'),
    ('gasto', 'streaming',        'suscripciones'),

    -- el resto
    ('gasto', 'gym',              'gimnasio'),
    ('gasto', 'peluqueria',       'cuidado personal'),
    ('gasto', 'peluquería',       'cuidado personal'),
    ('gasto', 'barberia',         'cuidado personal'),
    ('gasto', 'barbería',         'cuidado personal'),
    ('gasto', 'manicura',         'cuidado personal'),
    ('gasto', 'viaje',            'viajes'),
    ('gasto', 'vacaciones',       'viajes'),
    ('gasto', 'pasajes',          'viajes'),
    ('gasto', 'hotel',            'viajes'),
    ('gasto', 'mascota',          'mascotas'),
    ('gasto', 'perro',            'mascotas'),
    ('gasto', 'gato',             'mascotas'),
    ('gasto', 'veterinaria',      'mascotas'),
    ('gasto', 'regalo',           'regalos'),
    ('gasto', 'ferreteria',       'hogar'),
    ('gasto', 'ferretería',       'hogar'),
    ('gasto', 'muebles',          'hogar'),
    ('gasto', 'limpieza',         'hogar'),
    ('gasto', 'electronica',      'tecnologia'),
    ('gasto', 'electrónica',      'tecnologia'),
    ('gasto', 'tecnología',       'tecnologia'),
    ('gasto', 'salidas',          'ocio'),
    ('gasto', 'cine',             'ocio'),
    ('gasto', 'boliche',          'ocio'),
    ('gasto', 'teatro',           'ocio'),
    ('gasto', 'zapatillas',       'ropa'),
    ('gasto', 'calzado',          'ropa'),
    ('gasto', 'indumentaria',     'ropa'),

    -- ingresos
    ('ingreso', 'salario',        'sueldo'),
    ('ingreso', 'honorarios',     'freelance'),
    ('ingreso', 'laburito',       'freelance'),
    ('ingreso', 'venta',          'ventas'),
    ('ingreso', 'reintegro',      'reintegros'),
    ('ingreso', 'alquiler',       'alquileres'),

    -- ahorros e inversiones
    ('ahorro',    'plazo_fijo',   'plazo fijo'),
    ('ahorro',    'dólares',      'dolares'),
    ('ahorro',    'verdes',       'dolares'),
    ('inversion', 'dólares',      'dolares'),
    ('inversion', 'accion',       'acciones'),
    ('inversion', 'acción',       'acciones'),
    ('inversion', 'cedear',       'cedears'),
    ('inversion', 'bitcoin',      'cripto'),
    ('inversion', 'btc',          'cripto'),
    ('inversion', 'bono',         'bonos')
)
select
    mapa.tipo,
    mapa.desde                       as se_convierte,
    mapa.hacia                       as en,
    count(*)                         as movimientos,
    count(distinct m.user_id)        as usuarios
from mapa
join public.movimientos m
  on m.tipo = mapa.tipo
 and lower(trim(m.categoria)) = mapa.desde
group by mapa.tipo, mapa.desde, mapa.hacia
order by movimientos desc;


-- ===========================================================================
-- PARTE 2 - EL CAMBIO. Esto si reescribe.
--
-- Correr solo despues de mirar el resultado de la PARTE 1. El mapa tiene que
-- ser el mismo que arriba: si borraste una linea alla, borrala aca tambien.
--
-- POR QUE VA TODO DENTRO DE UN DO
-- El SQL Editor de Supabase no garantiza que dos sentencias seguidas caigan en
-- la misma sesion, asi que una tabla temporal creada en una sentencia puede no
-- existir en la siguiente: el 2026-09-14 esto fallo con `relation
-- "mapa_categorias" does not exist`. Dentro del DO es UNA sola sentencia --
-- una sesion, una transaccion -- y si algo revienta no se aplica nada. Por eso
-- tampoco lleva begin/commit propios.
--
-- El DO no devuelve filas: cuenta lo que hizo por NOTICE, y quien manda es la
-- comprobacion del final.
-- ===========================================================================

do $unificar$
declare
    faltan    text;
    cambiados integer;
    borradas  integer;
begin
    -- Repetible: si una corrida anterior murio a mitad de camino, la temporal
    -- puede haber quedado viva en esta misma sesion.
    drop table if exists pg_temp.mapa_categorias;

    create temporary table mapa_categorias (tipo text, desde text, hacia text) on commit drop;

    insert into mapa_categorias (tipo, desde, hacia) values
        ('gasto', 'super',            'supermercado'),
        ('gasto', 'súper',            'supermercado'),
        ('gasto', 'chino',            'supermercado'),
        ('gasto', 'almacen',          'supermercado'),
        ('gasto', 'almacén',          'supermercado'),
        ('gasto', 'verduleria',       'supermercado'),
        ('gasto', 'verdulería',       'supermercado'),
        ('gasto', 'carniceria',       'supermercado'),
        ('gasto', 'carnicería',       'supermercado'),
        ('gasto', 'panaderia',        'supermercado'),
        ('gasto', 'panadería',        'supermercado'),
        ('gasto', 'taxi',             'transporte'),
        ('gasto', 'uber',             'transporte'),
        ('gasto', 'cabify',           'transporte'),
        ('gasto', 'remis',            'transporte'),
        ('gasto', 'colectivo',        'transporte'),
        ('gasto', 'bondi',            'transporte'),
        ('gasto', 'sube',             'transporte'),
        ('gasto', 'subte',            'transporte'),
        ('gasto', 'tren',             'transporte'),
        ('gasto', 'peaje',            'transporte'),
        ('gasto', 'estacionamiento',  'transporte'),
        ('gasto', 'combustible',      'nafta'),
        ('gasto', 'ypf',              'nafta'),
        ('gasto', 'shell',            'nafta'),
        ('gasto', 'gnc',              'nafta'),
        ('gasto', 'gasoil',           'nafta'),
        ('gasto', 'luz',              'servicios'),
        ('gasto', 'gas',              'servicios'),
        ('gasto', 'agua',             'servicios'),
        ('gasto', 'internet',         'servicios'),
        ('gasto', 'telefono',         'servicios'),
        ('gasto', 'teléfono',         'servicios'),
        ('gasto', 'celular',          'servicios'),
        ('gasto', 'cable',            'servicios'),
        ('gasto', 'edesur',           'servicios'),
        ('gasto', 'edenor',           'servicios'),
        ('gasto', 'metrogas',         'servicios'),
        ('gasto', 'resto',            'comida'),
        ('gasto', 'restaurante',      'comida'),
        ('gasto', 'delivery',         'comida'),
        ('gasto', 'almuerzo',         'comida'),
        ('gasto', 'cena',             'comida'),
        ('gasto', 'desayuno',         'comida'),
        ('gasto', 'cafe',             'comida'),
        ('gasto', 'café',             'comida'),
        ('gasto', 'bar',              'comida'),
        ('gasto', 'kiosco',           'comida'),
        ('gasto', 'heladeria',        'comida'),
        ('gasto', 'heladería',        'comida'),
        ('gasto', 'farmacia',         'salud'),
        ('gasto', 'medico',           'salud'),
        ('gasto', 'médico',           'salud'),
        ('gasto', 'dentista',         'salud'),
        ('gasto', 'obra social',      'salud'),
        ('gasto', 'prepaga',          'salud'),
        ('gasto', 'psicologa',        'salud'),
        ('gasto', 'psicóloga',        'salud'),
        ('gasto', 'psicologo',        'salud'),
        ('gasto', 'psicólogo',        'salud'),
        ('gasto', 'educación',        'educacion'),
        ('gasto', 'colegio',          'educacion'),
        ('gasto', 'universidad',      'educacion'),
        ('gasto', 'curso',            'educacion'),
        ('gasto', 'libros',           'educacion'),
        ('gasto', 'monotributo',      'impuestos'),
        ('gasto', 'afip',             'impuestos'),
        ('gasto', 'arca',             'impuestos'),
        ('gasto', 'abl',              'impuestos'),
        ('gasto', 'patente',          'impuestos'),
        ('gasto', 'rentas',           'impuestos'),
        ('gasto', 'netflix',          'suscripciones'),
        ('gasto', 'spotify',          'suscripciones'),
        ('gasto', 'disney',           'suscripciones'),
        ('gasto', 'streaming',        'suscripciones'),
        ('gasto', 'gym',              'gimnasio'),
        ('gasto', 'peluqueria',       'cuidado personal'),
        ('gasto', 'peluquería',       'cuidado personal'),
        ('gasto', 'barberia',         'cuidado personal'),
        ('gasto', 'barbería',         'cuidado personal'),
        ('gasto', 'manicura',         'cuidado personal'),
        ('gasto', 'viaje',            'viajes'),
        ('gasto', 'vacaciones',       'viajes'),
        ('gasto', 'pasajes',          'viajes'),
        ('gasto', 'hotel',            'viajes'),
        ('gasto', 'mascota',          'mascotas'),
        ('gasto', 'perro',            'mascotas'),
        ('gasto', 'gato',             'mascotas'),
        ('gasto', 'veterinaria',      'mascotas'),
        ('gasto', 'regalo',           'regalos'),
        ('gasto', 'ferreteria',       'hogar'),
        ('gasto', 'ferretería',       'hogar'),
        ('gasto', 'muebles',          'hogar'),
        ('gasto', 'limpieza',         'hogar'),
        ('gasto', 'electronica',      'tecnologia'),
        ('gasto', 'electrónica',      'tecnologia'),
        ('gasto', 'tecnología',       'tecnologia'),
        ('gasto', 'salidas',          'ocio'),
        ('gasto', 'cine',             'ocio'),
        ('gasto', 'boliche',          'ocio'),
        ('gasto', 'teatro',           'ocio'),
        ('gasto', 'zapatillas',       'ropa'),
        ('gasto', 'calzado',          'ropa'),
        ('gasto', 'indumentaria',     'ropa'),
        ('ingreso', 'salario',        'sueldo'),
        ('ingreso', 'honorarios',     'freelance'),
        ('ingreso', 'laburito',       'freelance'),
        ('ingreso', 'venta',          'ventas'),
        ('ingreso', 'reintegro',      'reintegros'),
        ('ingreso', 'alquiler',       'alquileres'),
        ('ahorro',    'plazo_fijo',   'plazo fijo'),
        ('ahorro',    'dólares',      'dolares'),
        ('ahorro',    'verdes',       'dolares'),
        ('inversion', 'dólares',      'dolares'),
        ('inversion', 'accion',       'acciones'),
        ('inversion', 'acción',       'acciones'),
        ('inversion', 'cedear',       'cedears'),
        ('inversion', 'bitcoin',      'cripto'),
        ('inversion', 'btc',          'cripto'),
        ('inversion', 'bono',         'bonos');

    -- El destino tiene que existir como categoria base, o estariamos cambiando una
    -- etiqueta huerfana por otra. Si esto levanta, falta correr 019.
    select string_agg(distinct mapa.tipo || '/' || mapa.hacia, ', ')
      into faltan
      from mapa_categorias mapa
     where not exists (
         select 1 from public.categorias c
          where c.user_id is null and c.tipo = mapa.tipo and c.nombre = mapa.hacia
     );

    if faltan is not null then
        raise exception 'Estos destinos no existen como categoria base: %', faltan;
    end if;

    update public.movimientos m
       set categoria = mapa.hacia
      from mapa_categorias mapa
     where m.tipo = mapa.tipo
       and lower(trim(m.categoria)) = mapa.desde;

    get diagnostics cambiados = row_count;

    -- Las categorias propias que 019 importo desde esas etiquetas ya no apuntan a
    -- ningun movimiento: se van. Se borran SOLO las que estan en el mapa, no
    -- cualquiera que este vacia, para no llevarse puesta una que el usuario acabe
    -- de crear y todavia no haya usado.
    delete from public.categorias c
     using mapa_categorias mapa
     where c.user_id is not null
       and c.tipo   = mapa.tipo
       and c.nombre = mapa.desde;

    get diagnostics borradas = row_count;

    raise notice 'Movimientos reescritos: %. Categorias propias borradas: %.',
        cambiados, borradas;
end
$unificar$;


-- ---------------------------------------------------------------------------
-- Comprobacion. No modifica nada.
--
-- No tiene que quedar ninguna etiqueta del mapa dando vueltas: cero filas.
-- ---------------------------------------------------------------------------

select m.tipo, lower(trim(m.categoria)) as etiqueta, count(*) as movimientos
from public.movimientos m
where lower(trim(m.categoria)) in (
    'super', 'súper', 'chino', 'taxi', 'uber', 'combustible', 'luz', 'gas',
    'delivery', 'farmacia', 'monotributo', 'netflix', 'gym', 'salario'
)
group by m.tipo, etiqueta
order by movimientos desc;
