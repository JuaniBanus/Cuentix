-- Cerrar una inversion en vez de borrarla.
--
-- Una tenencia vendida sigue siendo parte del historial: el precio al que se
-- compro y la fecha son datos reales que no se recuperan si se borra la fila.
-- Por eso se marca, no se elimina.
--
-- `activa` arranca en true para que las filas que ya existen queden como estan:
-- el default cubre a las viejas y a las que inserte el bot sin nombrar la
-- columna, asi que ni db.py ni el parser necesitan cambiar para el alta.

alter table public.inversiones
    add column if not exists activa boolean not null default true;

-- Cuando se cerro. Null mientras siga abierta. Es lo que vuelve util al
-- historial: sin fecha, "cerrada" no dice cuando ni permite ordenar.
alter table public.inversiones
    add column if not exists cerrada_en date;

-- La pantalla filtra por dueño y por activa en la misma consulta.
create index if not exists inversiones_activas_idx
    on public.inversiones (user_id, activa);

-- Coherencia: una inversion abierta no puede tener fecha de cierre, y una
-- cerrada no puede no tenerla.
alter table public.inversiones
    drop constraint if exists inversiones_cierre_coherente;

alter table public.inversiones
    add constraint inversiones_cierre_coherente
    check ((activa and cerrada_en is null) or (not activa and cerrada_en is not null));


-- Comprobacion: todas las filas existentes quedaron activas y sin fecha.
select
    activa,
    count(*)                                   as filas,
    count(cerrada_en)                          as con_fecha_de_cierre
from public.inversiones
group by activa;
