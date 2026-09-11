"""El vocabulario de categorías: lo único que la IA puede elegir al etiquetar.

Antes el parser inventaba la categoría en el momento, y el mismo rubro entraba
un día como "super" y al otro como "supermercado". Acá vive la lista cerrada
—las base más las propias de cada usuario— y el emparejamiento entre lo que
dijo Gemini y esa lista.

La garantía no es el prompt, es este módulo: si el modelo devuelve algo que no
está en la lista, `Vocabulario.resolver()` devuelve None y el bot pregunta. Una
categoría nueva solo nace cuando el usuario la pide.

Sobre las tildes: los nombres nuevos se guardan sin ellas, como viene haciendo
el parser desde siempre, para que "cerámica" y "ceramica" no sean dos rubros.
Los importados de movimientos viejos conservan su texto exacto, porque tienen
que seguir coincidiendo letra a letra con lo que dice `movimientos.categoria`.
El emparejamiento ignora las tildes de los dos lados, así que da igual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import TipoMovimiento
from app.objetivos import normalizar

# Un nombre de categoría es una etiqueta, no una frase. Con más de esto el
# usuario está describiendo algo, y lo que quiere es una descripción.
MAXIMO_NOMBRE = 40
MAXIMO_PALABRAS = 3

# Cuántas alternativas se ofrecen cuando un gasto no encaja en ninguna.
CERCANAS = 3

# Piso para aceptar un parecido como "es la misma palabra con un typo".
# Alto a propósito: equivocarse de rubro en silencio es peor que preguntar.
# "gimnacio" contra "gimnasio" da 0.88; "yoga" contra "hogar", 0.67.
_PISO_PARECIDO = 0.86

# Piso para ofrecer un parecido como opción. Más bajo, porque acá elige el
# usuario y una opción de más no hace daño.
_PISO_SUGERENCIA = 0.7

# Desde cuántas letras una abreviatura cuenta como prefijo ("super").
_PREFIJO_MINIMO = 4

_ARTICULOS = ("la ", "el ", "los ", "las ", "una ", "un ", "mi ", "mis ")
_PREPOSICIONES = ("de ", "del ", "para ", "por ", "con ", "a ")

_SOLO_LETRAS = re.compile(r"^[a-záéíóúüñ ]+$")

# Lo que queda cuando alguien contesta "creála" o "una nueva" sin decir de qué:
# son restos de la frase, no nombres. Sin esto nacería la categoría "la".
_NO_SON_NOMBRES = frozenset(
    {
        "categoria", "categorias", "otros", "otro", "nada", "ninguna", "ninguno",
        "la", "el", "los", "las", "un", "una", "unos", "unas", "lo",
        "mi", "mis", "tu", "tus", "su", "sus", "de", "del", "para", "por",
        "esa", "ese", "eso", "esta", "este", "esto", "ahi", "asi", "igual",
        "si", "no", "dale", "ok", "bueno", "gracias",
    }
)


@dataclass(frozen=True)
class Categoria:
    """Una etiqueta disponible. `propia` distingue las del usuario de las base."""

    nombre: str
    tipo: TipoMovimiento
    emoji: str | None = None
    propia: bool = False

    @property
    def etiqueta(self) -> str:
        """Cómo se muestra en un mensaje: '🛒 supermercado'."""
        return f"{self.emoji} {self.nombre}" if self.emoji else self.nombre


def _clave(texto: str) -> str:
    """La forma comparable de un nombre: sin tildes, sin signos, sin dobles espacios."""
    return normalizar(texto)


def _singular(clave: str) -> str:
    """"mascotas" -> "mascota". Para que un plural no cuente como otro rubro."""
    if len(clave) > 3 and clave.endswith("s"):
        return clave[:-1]
    return clave


def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


class Vocabulario:
    """Las categorías que un usuario puede usar: las base más las suyas."""

    def __init__(self, categorias: list[Categoria]):
        self._por_tipo: dict[TipoMovimiento, list[Categoria]] = {}
        for categoria in categorias:
            self._por_tipo.setdefault(categoria.tipo, []).append(categoria)

    def __bool__(self) -> bool:
        return any(self._por_tipo.values())

    def de(self, tipo: TipoMovimiento) -> list[Categoria]:
        """Las categorías de ese tipo, con las propias al final."""
        return sorted(
            self._por_tipo.get(tipo, ()), key=lambda c: (c.propia, c.nombre)
        )

    def propias(self) -> list[Categoria]:
        """Las que creó el usuario: las únicas que puede borrar."""
        return sorted(
            (c for lista in self._por_tipo.values() for c in lista if c.propia),
            key=lambda c: (c.tipo.value, c.nombre),
        )

    def otros(self, tipo: TipoMovimiento) -> str:
        """El nombre del cajón de sastre de ese tipo.

        019_categorias.sql lo crea como base para los cuatro tipos y RLS no deja
        borrar una base, así que siempre existe. El fallback es por si alguien
        corre el bot contra una base a medio migrar.
        """
        encontrada = self.resolver("otros", tipo)
        return encontrada.nombre if encontrada else "otros"

    def resolver(self, nombre: str | None, tipo: TipoMovimiento) -> Categoria | None:
        """La categoría que corresponde a ese texto, o None si no encaja en ninguna.

        Es lo que convierte la lista en una garantía: lo que devuelve Gemini pasa
        por acá antes de llegar a la base.
        """
        clave = _clave(nombre or "")
        if not clave:
            return None

        candidatas = self._por_tipo.get(tipo, ())
        if not candidatas:
            return None

        for candidata in candidatas:
            if _clave(candidata.nombre) == clave:
                return candidata

        singular = _singular(clave)
        for candidata in candidatas:
            if _singular(_clave(candidata.nombre)) == singular:
                return candidata

        # Una abreviatura es un prefijo: "super" es supermercado, "cripto" es
        # cripto. Solo vale si no hay dos categorías que empiecen igual, porque
        # entonces no se sabe cuál quiso.
        if len(clave) >= _PREFIJO_MINIMO:
            empiezan = [
                c for c in candidatas if _clave(c.nombre).startswith(clave)
            ]
            if len(empiezan) == 1:
                return empiezan[0]

        # Un typo se perdona; una palabra distinta no. Si dos categorías empatan
        # cerca, es ambiguo y prefiero preguntar.
        puntuadas = sorted(
            ((_parecido(clave, _clave(c.nombre)), c) for c in candidatas),
            key=lambda par: par[0],
            reverse=True,
        )
        mejor, categoria = puntuadas[0]
        if mejor < _PISO_PARECIDO:
            return None
        if len(puntuadas) > 1 and puntuadas[1][0] >= _PISO_PARECIDO:
            return None
        return categoria

    def resolver_en_cualquier_tipo(
        self, nombre: str | None, tipo: TipoMovimiento | None = None
    ) -> Categoria | None:
        """Igual que `resolver`, para cuando no se sabe de qué tipo es.

        Las consultas no siempre dicen el tipo: "¿cuánto gasté en súper?" trae
        un rubro pero "¿cuánto llevo en dólares?" no. Sin esto, el filtro se
        armaría con la palabra del usuario y devolvería cero.
        """
        if tipo is not None:
            return self.resolver(nombre, tipo)
        for candidato in TipoMovimiento:
            encontrada = self.resolver(nombre, candidato)
            if encontrada is not None:
                return encontrada
        return None

    def mas_cercanas(
        self,
        mencion: str,
        tipo: TipoMovimiento,
        frecuentes: tuple[str, ...] = (),
        cantidad: int = CERCANAS,
    ) -> list[Categoria]:
        """Las alternativas que se le ofrecen al usuario cuando nada encaja.

        El parecido letra a letra sirve para pescar un typo, no para sugerir:
        "yoga" se parece más a "hogar" (0.67) que a cualquier cosa razonable, y
        ofrecer eso es ruido. Así que arriba va lo que podría ser un typo, y el
        resto se llena con lo que el usuario más usa, que es la única señal de
        verdad que hay.

        Deja afuera "otros": esa opción ya la cubre el «dejalo» de la pregunta.
        """
        clave = _clave(mencion)
        candidatas = [
            c for c in self._por_tipo.get(tipo, ()) if _clave(c.nombre) != "otros"
        ]

        elegidas: list[Categoria] = []

        puntuadas = sorted(
            ((_parecido(clave, _clave(c.nombre)), c.nombre, c) for c in candidatas),
            key=lambda par: (-par[0], par[1]),
        )
        elegidas += [c for valor, _, c in puntuadas if valor >= _PISO_SUGERENCIA]

        por_nombre = {_clave(c.nombre): c for c in candidatas}
        for nombre in frecuentes:
            candidata = por_nombre.get(_clave(nombre))
            if candidata is not None and candidata not in elegidas:
                elegidas.append(candidata)

        return elegidas[:cantidad]

    def para_prompt(self) -> str:
        """La lista como la ve Gemini, agrupada por tipo."""
        lineas = []
        for tipo in TipoMovimiento:
            nombres = [c.nombre for c in self.de(tipo)]
            if nombres:
                lineas.append(f"  {tipo.value + ':':<11}{' · '.join(nombres)}")
        return "\n".join(lineas)


_ETIQUETA_TIPO = {
    TipoMovimiento.GASTO: "GASTOS",
    TipoMovimiento.INGRESO: "INGRESOS",
    TipoMovimiento.AHORRO: "AHORROS",
    TipoMovimiento.INVERSION: "INVERSIONES",
}


def formatear_listado(vocabulario: Vocabulario) -> str:
    """El mensaje de «¿qué categorías tengo?»."""
    bloques = ["🏷 Tus categorías"]

    for tipo, titulo in _ETIQUETA_TIPO.items():
        categorias = vocabulario.de(tipo)
        if not categorias:
            continue

        base = [c.etiqueta for c in categorias if not c.propia]
        propias = [f"✏️ {c.nombre}" for c in categorias if c.propia]

        lineas = [f"\n{titulo}"]
        if base:
            lineas.append(" · ".join(base))
        if propias:
            lineas.append(" · ".join(propias))
        bloques.append("\n".join(lineas))

    if vocabulario.propias():
        bloques.append("\nLas de ✏️ son tuyas: esas las podés borrar.")
    else:
        bloques.append(
            "\nTodavía no tenés ninguna propia. Si te falta un rubro, decime "
            "«creá la categoría X» y te la sumo."
        )

    return "\n".join(bloques)


def nombre_valido(texto: str | None) -> str | None:
    """El nombre listo para guardar, o None si eso no es un nombre de categoría.

    Filtra lo que llega tanto de Gemini como de una respuesta suelta del usuario:
    sin esto, un mensaje cualquiera que caiga mientras hay una pregunta abierta
    se convertiría en una categoría fantasma.
    """
    limpio = _clave(texto or "")

    # Hay que volver a pasar por la lista entera después de sacar uno: en "para
    # mis clases de yoga" el "mis" recién queda al frente cuando se fue el
    # "para", y una sola pasada lo dejaría adentro.
    recortando = True
    while recortando:
        recortando = False
        for prefijo in _ARTICULOS + _PREPOSICIONES:
            if limpio.startswith(prefijo):
                limpio = limpio[len(prefijo) :].strip()
                recortando = True

    limpio = limpio.strip()
    if len(limpio) < 2 or len(limpio) > MAXIMO_NOMBRE:
        return None
    if len(limpio.split()) > MAXIMO_PALABRAS:
        return None
    if not _SOLO_LETRAS.match(limpio):
        return None
    if limpio in _NO_SON_NOMBRES:
        return None
    return limpio


# ---------------------------------------------------------------------------
# Comandos que no necesitan a Gemini
#
# El bot tiene un cupo de 20 llamadas por hora (LIMITE_GEMINI en app/main.py).
# Listar las categorías es lo más frecuente y no tiene nada que interpretar, así
# que va por acá. Las formas sueltas —"agregá una categoría para mis clases de
# yoga"— sí pasan por el parser, que sabe sacar "yoga" de ahí.
# ---------------------------------------------------------------------------

_LISTAR = frozenset(
    {
        "/categorias",
        "categorias",
        "mis categorias",
        "que categorias tengo",
        "cuales son mis categorias",
        "mostrame mis categorias",
        "mostrame las categorias",
        "ver categorias",
        "lista de categorias",
        "listar categorias",
        "lista mis categorias",
    }
)

_CREAR = re.compile(
    r"^(?:crearme|crearte|creame|crear|crea|agregarme|agregame|agregar|agrega|"
    r"sumarme|sumame|sumar|suma|anotar|anota|quiero|necesito|nueva|nuevo)\b\s+"
    r"(?:una\s+|la\s+|el\s+|un\s+)?"
    r"categoria\s*:?\s*(?P<nombre>.+)$"
)

_BORRAR = re.compile(
    r"^(?:borrarme|borrame|borrar|borra|eliminar|elimina|sacar|saca|quitar|quita)"
    r"\b\s+"
    r"(?:la\s+|el\s+|una\s+|mi\s+)?"
    r"categoria\s*:?\s*(?P<nombre>.+)$"
)


@dataclass(frozen=True)
class Gestion:
    """Lo que el usuario pidió hacer con sus categorías."""

    accion: str  # listar | crear | borrar
    nombre: str | None = None


def leer_comando(texto: str) -> Gestion | None:
    """Interpreta las formas directas sin gastar una llamada a Gemini.

    None significa "esto no es un comando de categorías", no "no entendí": el
    mensaje sigue su camino normal hacia el parser.
    """
    clave = _clave(texto)
    if clave.startswith("/"):
        clave = clave.split("@", 1)[0]

    if clave in _LISTAR:
        return Gestion(accion="listar")

    coincidencia = _CREAR.match(clave)
    if coincidencia:
        nombre = nombre_valido(coincidencia.group("nombre"))
        return Gestion(accion="crear", nombre=nombre) if nombre else None

    coincidencia = _BORRAR.match(clave)
    if coincidencia:
        nombre = nombre_valido(coincidencia.group("nombre"))
        return Gestion(accion="borrar", nombre=nombre) if nombre else None

    return None


# La respuesta a "¿dónde va este gasto?" cuando el usuario quiere una nueva.
# Se exige el verbo: un nombre suelto se empareja contra lo que ya existe, nunca
# crea. Si no, "gasté 2 lucas en el kiosco" mandado mientras hay una pregunta
# abierta terminaría siendo una categoría llamada "gaste 2 lucas en el kiosco".
_CREAR_EN_RESPUESTA = re.compile(
    r"^(?:crearla|crearle|creala|creame|crear|crea|agregarla|agregala|agregar|"
    r"agrega|sumarla|sumala|sumar|suma|nueva|nuevo)\b"
    r"(?:\s+(?:una\s+|la\s+|el\s+|un\s+)?categoria)?\s*:?\s*(?P<nombre>.*)$"
)


def leer_creacion(texto: str, sugerido: str | None = None) -> str | None:
    """El nombre a crear si la respuesta pide una categoría nueva, o None.

    `sugerido` es lo que el bot venía preguntando: permite contestar «creála» a
    secas sin repetir el nombre.
    """
    coincidencia = _CREAR_EN_RESPUESTA.match(_clave(texto))
    if not coincidencia:
        return None
    return nombre_valido(coincidencia.group("nombre")) or nombre_valido(sugerido)
