"""Quién escribe: del chat_id de Telegram al user_id de Supabase.

Este módulo es el control de acceso del bot. Antes había una constante —
CHATS_PERMITIDOS en el .env— y un único dueño para todo lo que se guardaba
(SUPABASE_USER_ID). Con varios usuarios eso no alcanza: hay que saber de QUIÉN
es cada mensaje antes de leer o escribir una sola fila.

POR QUÉ ESTO ES CRÍTICO Y NO UN DETALLE
El bot habla con Supabase usando la clave service_role, que SALTEA RLS por
diseño. O sea: las policies que aíslan a los usuarios en el navegador acá no
corren. Del lado del bot, el aislamiento es exactamente esto —resolver el
usuario— más el filtro por user_id que lleva cada consulta de app/db.py. Si
alguna de las dos mitades falta, el bot lee y escribe la base entera.

FALLA CERRADA
`resolver()` devuelve None ante cualquier duda: chat sin vincular, perfil que
no existe, error de red contra Supabase. Nunca devuelve un usuario "por
defecto". Quien llama no puede confundir "no sé quién sos" con "sos el dueño":
lo primero que se hace con None es no procesar el mensaje.

Es al revés de casi todo el resto del bot, donde un error de lectura se degrada
en silencio para no dejar al usuario sin respuesta (obtener_inversiones
devuelve [], por ejemplo). Acá no se puede degradar: seguir sin saber de quién
es el mensaje sería seguir sin saber a qué cuenta escribirlo.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.db import DBError, perfil_de, vinculo_de_chat

logger = logging.getLogger(__name__)

# Cuánto vale una respuesta cacheada. Sesenta segundos es el equilibrio entre
# no consultar dos tablas en cada mensaje y que pausar una cuenta tenga efecto
# enseguida: quien la pausa espera que deje de andar ya, no en media hora.
#
# La consecuencia hay que decirla: durante hasta un minuto, un usuario recién
# pausado puede seguir cargando movimientos. Si eso no sirve para un caso, se
# baja a 0 y cada mensaje consulta la base.
VIGENCIA_CACHE = 60.0

ESTADO_HABILITADO = "activo"


@dataclass(frozen=True)
class Usuario:
    """El dueño de un chat, ya resuelto y con su estado de cuenta."""

    chat_id: int
    user_id: str
    email: str
    estado: str

    @property
    def habilitado(self) -> bool:
        """Solo 'activo' puede usar el bot.

        'pausado' y 'pendiente' quedan afuera con el mismo mensaje neutro: para
        quien escribe son el mismo hecho —no tenés acceso—, y distinguirlos le
        diría a un desconocido si una cuenta existe o no.
        """
        return self.estado == ESTADO_HABILITADO


# chat_id -> (cuándo se resolvió, resultado). El None también se cachea: si no,
# un chat ajeno que mande veinte mensajes serían veinte pares de consultas.
_cache: dict[int, tuple[float, Usuario | None]] = {}


def resolver(chat_id: int) -> Usuario | None:
    """El usuario dueño de ese chat, o None si no lo hay o no se pudo saber.

    None significa "no proceses el mensaje". Nunca significa "usá el usuario
    por defecto", porque no hay usuario por defecto.
    """
    ahora = time.monotonic()

    guardado = _cache.get(chat_id)
    if guardado is not None and ahora - guardado[0] < VIGENCIA_CACHE:
        return guardado[1]

    usuario = _consultar(chat_id)
    _cache[chat_id] = (ahora, usuario)
    return usuario


def _consultar(chat_id: int) -> Usuario | None:
    """Las dos consultas: el vínculo y después el perfil.

    Son dos y no un join embebido de PostgREST porque `usuarios_telegram` y
    `perfiles` no tienen una FK directa entre sí que PostgREST pueda inferir
    (las dos apuntan a auth.users). Dos viajes cada 60 segundos por chat es un
    costo que no se nota, y a cambio esto no depende de cómo PostgREST adivine
    las relaciones.
    """
    try:
        vinculo = vinculo_de_chat(chat_id)
    except DBError:
        # No se pudo preguntar. No se asume nada: se rechaza y se reintenta en
        # el mensaje siguiente, cuando el caché venza.
        logger.exception("No pude resolver el chat %s contra usuarios_telegram", chat_id)
        return None

    if vinculo is None:
        logger.warning("Chat %s sin vincular: no hay fila en usuarios_telegram", chat_id)
        return None

    user_id = str(vinculo.get("user_id") or "")
    if not user_id:
        # La columna es NOT NULL en la base, así que esto no debería pasar.
        # Se contempla igual: una fila rota no puede terminar en un user_id
        # vacío que después viaje a un .eq() y no filtre nada.
        logger.error("El vínculo del chat %s no tiene user_id", chat_id)
        return None

    try:
        perfil = perfil_de(user_id)
    except DBError:
        logger.exception("No pude leer el perfil de %s", user_id)
        return None

    if perfil is None:
        # Vínculo apuntando a un usuario sin perfil. Sin perfil no hay estado
        # que mirar, así que no se habilita.
        logger.error("El usuario %s del chat %s no tiene perfil", user_id, chat_id)
        return None

    usuario = Usuario(
        chat_id=chat_id,
        user_id=user_id,
        email=str(perfil.get("email") or ""),
        estado=str(perfil.get("estado") or ""),
    )

    if not usuario.habilitado:
        logger.warning(
            "Chat %s vinculado a %s, pero la cuenta está %r",
            chat_id, usuario.email, usuario.estado,
        )

    return usuario


def olvidar(chat_id: int) -> None:
    """Descarta lo cacheado de un chat, para que el próximo mensaje relea.

    Se usa cuando algo hace sospechar que el estado cambió, y en los tests.
    """
    _cache.pop(chat_id, None)


def limpiar() -> None:
    """Vacía el caché entero. Solo para los tests."""
    _cache.clear()
