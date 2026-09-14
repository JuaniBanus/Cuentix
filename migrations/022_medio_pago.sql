-- Como se pago o se cobro cada movimiento.
--
-- POR QUE UNA COLUMNA NUEVA Y NO `cuenta`
-- Son dos preguntas distintas que muchas veces conviven:
--   cuenta     = DONDE esta la plata (efectivo, banco, billetera, broker)
--   medio_pago = COMO se movio      (efectivo, debito, credito, transferencia)
-- "pague con debito del Galicia" tiene las dos: medio=debito, cuenta=banco. Con
-- una sola columna se pierde una.
--
-- Y sobre todo: una tarjeta de credito NO es una cuenta. No es un lugar donde
-- tenes plata, es una deuda. Meterla en `cuenta` haria que cualquier vista de
-- "donde esta mi plata" sume un saldo que no existe. La web ya tiene una
-- pantalla de gastos por cuenta (web/js/cuentas.js) que leeria mal ese dato, y
-- se sube a mano a Hostinger, asi que quedaria rota hasta la proxima subida.
--
-- POR QUE UN CHECK Y NO UNA TABLA COMO categorias
-- Los medios de pago son cinco y no los inventa el usuario: son los que existen
-- en el mundo. Una tabla con ABM seria maquinaria para un vocabulario que no
-- cambia. Las categorias son al reves, y por eso si tienen tabla.
--
-- Idempotente: se puede volver a correr sin romper nada.


alter table public.movimientos
    add column if not exists medio_pago text;


-- El CHECK se agrega aparte y con guarda, porque `add column if not exists` no
-- vuelve a aplicarlo si la columna ya estaba.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'movimientos_medio_pago_check'
    ) then
        alter table public.movimientos
            add constraint movimientos_medio_pago_check
            check (medio_pago is null or medio_pago in (
                'efectivo', 'debito', 'credito', 'transferencia', 'billetera'
            ));
    end if;
end $$;


-- Parcial: la enorme mayoria de las filas va a tener medio_pago en null (solo
-- se completa cuando el usuario lo dice), y esas no hace falta indexarlas.
create index if not exists movimientos_medio_pago_idx
    on public.movimientos (user_id, medio_pago)
    where medio_pago is not null;


-- ---------------------------------------------------------------------------
-- Poner en su lugar lo que ya se habia colado
--
-- Antes de que existiera esta columna, "lo pague con la tarjeta" no tenia donde
-- ir y termino en `cuenta`. Al 14/09/2026 habia una sola fila asi. Una tarjeta
-- no es un lugar donde este la plata, asi que la etiqueta se muda y `cuenta`
-- queda en null, que es la respuesta correcta cuando no se sabe de donde salio.
--
-- Las otras que tienen `cuenta` ('banco', 'billetera virtual') SI son ubicacion
-- y no se tocan.
-- ---------------------------------------------------------------------------

update public.movimientos
   set medio_pago = 'credito',
       cuenta     = null
 where medio_pago is null
   and lower(trim(cuenta)) in (
       'tarjeta de credito', 'tarjeta de crédito', 'tarjeta', 'credito', 'crédito'
   );

update public.movimientos
   set medio_pago = 'debito',
       cuenta     = null
 where medio_pago is null
   and lower(trim(cuenta)) in (
       'tarjeta de debito', 'tarjeta de débito', 'debito', 'débito'
   );


-- ---------------------------------------------------------------------------
-- Comprobaciones. No modifican nada.
-- ---------------------------------------------------------------------------

-- Que quedo cargado, y cuanto sigue sin dato (que es lo normal y esperable).
select
    coalesce(medio_pago, '(sin registrar)') as medio,
    count(*)                                as movimientos
from public.movimientos
group by medio_pago
order by movimientos desc;

-- Ninguna fila puede tener una tarjeta metida en `cuenta`. TIENE QUE DAR CERO.
select count(*) as tarjetas_mal_ubicadas
from public.movimientos
where lower(trim(cuenta)) like '%tarjeta%'
   or lower(trim(cuenta)) in ('credito', 'crédito', 'debito', 'débito');
