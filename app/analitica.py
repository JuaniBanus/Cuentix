"""Ejecuta un PlanConsulta y redacta la respuesta en castellano.

POR QUÉ ESTO EXISTE Y NO "QUE GEMINI ESCRIBA LA CONSULTA"

La tentación es pedirle SQL al modelo y ejecutarlo. Es más corto de escribir y
mucho peor:

- Un modelo que emite SQL puede emitir `delete`, `update`, un `union` contra
  otra tabla o un `pg_sleep`. Aunque el 99,9% de las veces genere un `select`
  inocente, la superficie de ataque es "todo lo que Postgres entiende", y quien
  escribe el texto de entrada es cualquiera que le escriba al bot.
- Una consulta mal armada no falla ruidosamente: devuelve un número. El usuario
  lee "gastaste $84.000" sin forma de saber que se contaron también los ahorros.
- Con service_role, que saltea RLS, un SQL suelto puede leer filas de otro
  usuario.

Acá el modelo NO produce consulta: produce un PlanConsulta, que es un objeto
con campos tipados y enums cerrados. La traducción de plan a consulta la hace
este archivo, con un repertorio fijo. Lo que no está previsto, no se puede
pedir; y si el modelo devuelve algo fuera del vocabulario, Pydantic lo rechaza
antes de que toque la base.

Las agregaciones se hacen en Python sobre las filas ya filtradas. A escala de
finanzas personales el costo es nulo, se mantiene la exactitud con Decimal, y
—lo importante— no hay ningún punto donde un texto del usuario se convierta en
parte de una consulta.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.db import movimientos_para_analisis
from app.models import (
    Agregacion,
    BasePromedio,
    Dimension,
    DiaSemana,
    Moneda,
    Periodo,
    PlanConsulta,
)

logger = logging.getLogger(__name__)

# Techo de grupos que se muestran, por encima del que pida el plan.
TOPE_GRUPOS = 12

_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_DIAS_LINDOS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_ETIQUETA_TIPO = {
    "gasto": "gastos", "ingreso": "ingresos",
    "ahorro": "ahorros", "inversion": "inversiones",
}


class Grupo:
    """Un renglón del resultado: su etiqueta y los números de ese conjunto."""

    __slots__ = ("etiqueta", "total", "cantidad", "maximo", "minimo", "dias", "meses")

    def __init__(self, etiqueta: str) -> None:
        self.etiqueta = etiqueta
        self.total = Decimal("0")
        self.cantidad = 0
        self.maximo: tuple[Decimal, str] | None = None
        self.minimo: tuple[Decimal, str] | None = None
        self.dias: set[date] = set()
        self.meses: set[tuple[int, int]] = set()

    def sumar(self, fila: dict, monto: Decimal, cuando: date) -> None:
        self.total += monto
        self.cantidad += 1
        self.dias.add(cuando)
        self.meses.add((cuando.year, cuando.month))
        detalle = (fila.get("descripcion") or fila.get("categoria") or "").strip()
        if self.maximo is None or monto > self.maximo[0]:
            self.maximo = (monto, detalle)
        if self.minimo is None or monto < self.minimo[0]:
            self.minimo = (monto, detalle)

    def valor(self, plan: PlanConsulta) -> Decimal:
        """El número que pidió la pregunta."""
        if plan.agregacion is Agregacion.CANTIDAD:
            return Decimal(self.cantidad)
        if plan.agregacion is Agregacion.MAXIMO:
            return self.maximo[0] if self.maximo else Decimal("0")
        if plan.agregacion is Agregacion.MINIMO:
            return self.minimo[0] if self.minimo else Decimal("0")
        if plan.agregacion is Agregacion.PROMEDIO:
            if plan.base_promedio is BasePromedio.DIA:
                divisor = len(self.dias)
            elif plan.base_promedio is BasePromedio.MES:
                divisor = len(self.meses)
            else:
                divisor = self.cantidad
            if not divisor:
                return Decimal("0")
            return (self.total / divisor).quantize(Decimal("0.01"))
        return self.total


class Resultado:
    """Lo que devuelve ejecutar un plan, ya listo para redactar."""

    def __init__(self) -> None:
        # (moneda, etiqueta) -> Grupo. La moneda SIEMPRE separa: sumar pesos
        # con dólares daría un número sin significado, igual que en el resto
        # de la app.
        self.grupos: dict[Moneda, list[Grupo]] = {}
        self.filas = 0


def _clave(fila: dict, dimension: Dimension, cuando: date) -> str:
    """La etiqueta del grupo al que pertenece la fila."""
    if dimension is Dimension.CATEGORIA:
        return (fila.get("categoria") or "sin categoría").strip()
    if dimension is Dimension.COMERCIO:
        return (fila.get("descripcion") or fila.get("categoria") or "sin detalle").strip()
    if dimension is Dimension.DIA_SEMANA:
        return _DIAS_LINDOS[cuando.weekday()]
    if dimension is Dimension.MES:
        return f"{_MESES[cuando.month - 1]} {cuando.year}"
    if dimension is Dimension.TIPO:
        return _ETIQUETA_TIPO.get(fila.get("tipo", ""), fila.get("tipo", ""))
    if dimension is Dimension.MONEDA:
        return fila.get("moneda", "")
    if dimension is Dimension.CUENTA:
        return (fila.get("cuenta") or "sin cuenta").strip()
    return "total"


def ejecutar(
    plan: PlanConsulta, periodo: Periodo | None = None, *, user_id: str
) -> Resultado:
    """Corre el plan sobre un período y devuelve los grupos calculados.

    `user_id` es de quién es la pregunta. Va como parámetro y no como algo que
    este módulo pueda averiguar solo, para que no exista ninguna forma de pedir
    un análisis sin decir sobre los datos de quién.
    """
    ventana = periodo or plan.periodo

    filas = movimientos_para_analisis(
        user_id=user_id,
        desde=ventana.desde,
        hasta=ventana.hasta,
        tipo=plan.tipo,
        moneda=plan.moneda,
        categoria=plan.categoria,
        comercio=plan.comercio,
    )

    # El día de la semana no se puede filtrar en PostgREST sin una función en
    # la base, así que se filtra acá. Es el único filtro que no viaja al motor.
    dias_pedidos = {d.value for d in plan.dias_semana}

    resultado = Resultado()
    acumulado: dict[Moneda, dict[str, Grupo]] = defaultdict(dict)

    for fila in filas:
        try:
            cuando = date.fromisoformat(fila["fecha"])
            monto = Decimal(str(fila["monto"]))
            moneda = Moneda(fila["moneda"])
        except (KeyError, ValueError, TypeError):
            logger.warning("Fila ilegible en el análisis: %r", fila)
            continue

        if dias_pedidos and _DIAS[cuando.weekday()] not in dias_pedidos:
            continue

        etiqueta = _clave(fila, plan.agrupar_por, cuando)
        grupo = acumulado[moneda].get(etiqueta)
        if grupo is None:
            grupo = acumulado[moneda][etiqueta] = Grupo(etiqueta)
        grupo.sumar(fila, monto, cuando)
        resultado.filas += 1

    for moneda, grupos in acumulado.items():
        ordenados = sorted(grupos.values(), key=lambda g: g.valor(plan), reverse=True)
        resultado.grupos[moneda] = ordenados

    return resultado


# --------------------------------------------------------------------------
# Redacción
# --------------------------------------------------------------------------


def _sujeto(plan: PlanConsulta) -> str:
    """"tus gastos", "lo que cobraste", "tus movimientos"."""
    if plan.tipo is None:
        return "tus movimientos"
    return "tus " + _ETIQUETA_TIPO.get(plan.tipo.value, "movimientos")


def _detalle_filtros(plan: PlanConsulta) -> str:
    partes = []
    if plan.categoria:
        partes.append(f"en {plan.categoria}")
    if plan.comercio:
        partes.append(f"que mencionan «{plan.comercio}»")
    if plan.dias_semana:
        # En plural: "los sábados y domingos", no "los sábado y domingo".
        nombres = [
            _DIAS_LINDOS[_DIAS.index(d.value)] + ("" if d.value.endswith("s") else "s")
            for d in plan.dias_semana
        ]
        partes.append("los " + " y ".join(nombres))
    return " " + " ".join(partes) if partes else ""


def _periodo_en_texto(periodo: Periodo) -> str:
    """"en total" es el default cuando la pregunta no acota el tiempo, y
    repetirlo suena raro ("...que mencionan «starbucks» en total")."""
    return "" if periodo.etiqueta == "en total" else f" {periodo.etiqueta}"


def _nombre_agregacion(plan: PlanConsulta) -> str:
    if plan.agregacion is Agregacion.PROMEDIO:
        return {
            BasePromedio.DIA: "Promedio por día",
            BasePromedio.MES: "Promedio por mes",
            BasePromedio.MOVIMIENTO: "Promedio",
        }[plan.base_promedio]
    return {
        Agregacion.TOTAL: "Total",
        Agregacion.MAXIMO: "El más grande",
        Agregacion.MINIMO: "El más chico",
        Agregacion.CANTIDAD: "Cantidad",
    }[plan.agregacion]


def redactar(
    plan: PlanConsulta,
    resultado: Resultado,
    formatear_monto,
    comparacion: Resultado | None = None,
) -> str:
    """Arma el texto de la respuesta.

    `formatear_monto(monto, moneda)` lo inyecta main.py para no duplicar el
    formato argentino ni la lógica del ojo.
    """
    periodo = _periodo_en_texto(plan.periodo)

    if not resultado.grupos:
        return f"No tengo {_sujeto(plan)}{_detalle_filtros(plan)}{periodo} 🤷"

    lineas: list[str] = []
    encabezado = f"{_nombre_agregacion(plan)} de {_sujeto(plan)}{_detalle_filtros(plan)}"
    lineas.append(f"{encabezado}{periodo}:")

    tope = min(plan.limite, TOPE_GRUPOS)
    # Con dos monedas en juego y agrupado, las etiquetas se repiten ("sin
    # cuenta" para pesos y para dólares) y sin encabezado no se sabe cuál es cuál.
    marcar_moneda = len(resultado.grupos) > 1 and plan.agrupar_por is not Dimension.NINGUNA

    for moneda in sorted(resultado.grupos, key=lambda m: m.value):
        grupos = resultado.grupos[moneda]

        if plan.agrupar_por is Dimension.NINGUNA:
            grupo = grupos[0]
            lineas.append(f"  {_texto_valor(plan, grupo, moneda, formatear_monto)}")
            continue

        if marcar_moneda:
            lineas.append(f"— {moneda.value} —")

        for grupo in grupos[:tope]:
            lineas.append(
                f"  {grupo.etiqueta}: {_texto_valor(plan, grupo, moneda, formatear_monto)}"
            )
        if len(grupos) > tope:
            lineas.append(f"  …y {len(grupos) - tope} más")

    if comparacion is not None:
        lineas.append("")
        lineas.append(_texto_comparacion(plan, resultado, comparacion, formatear_monto))

    return "\n".join(lineas)


def _texto_valor(plan: PlanConsulta, grupo: Grupo, moneda: Moneda, fmt) -> str:
    if plan.agregacion is Agregacion.CANTIDAD:
        n = grupo.cantidad
        return f"{n} movimiento{'' if n == 1 else 's'}"

    valor = fmt(grupo.valor(plan), moneda)

    if plan.agregacion in (Agregacion.MAXIMO, Agregacion.MINIMO):
        extremo = grupo.maximo if plan.agregacion is Agregacion.MAXIMO else grupo.minimo
        detalle = extremo[1] if extremo and extremo[1] else ""
        return f"{valor}{f' ({detalle})' if detalle else ''}"

    if plan.agregacion is Agregacion.PROMEDIO:
        return f"{valor} (sobre {grupo.cantidad} movimiento{'' if grupo.cantidad == 1 else 's'})"

    return f"{valor} ({grupo.cantidad} movimiento{'' if grupo.cantidad == 1 else 's'})"


def _texto_comparacion(
    plan: PlanConsulta, actual: Resultado, previo: Resultado, fmt
) -> str:
    """La comparación entre dos períodos, moneda por moneda.

    Son dos ejecuciones del mismo plan sobre ventanas distintas y una resta.
    No hay subconsulta ni SQL: eso es lo que hace que agregar comparativas no
    amplíe en nada la superficie de lo que se puede pedir.
    """
    lineas = [f"Contra {previo_etiqueta(plan)}:"]

    monedas = sorted(set(actual.grupos) | set(previo.grupos), key=lambda m: m.value)
    for moneda in monedas:
        total_actual = sum((g.total for g in actual.grupos.get(moneda, [])), Decimal("0"))
        total_previo = sum((g.total for g in previo.grupos.get(moneda, [])), Decimal("0"))
        diferencia = total_actual - total_previo

        if total_previo == 0:
            comentario = "no tengo nada del período anterior para comparar"
        else:
            pct = (diferencia / total_previo) * 100
            verbo = "más" if diferencia > 0 else "menos" if diferencia < 0 else "igual"
            if diferencia == 0:
                comentario = "exactamente igual"
            else:
                comentario = (
                    f"{fmt(abs(diferencia), moneda)} {verbo} "
                    f"({abs(pct):.0f}%)"
                )

        lineas.append(
            f"  {fmt(total_previo, moneda)} → {fmt(total_actual, moneda)} · {comentario}"
        )

    return "\n".join(lineas)


def previo_etiqueta(plan: PlanConsulta) -> str:
    return plan.comparar_con.etiqueta if plan.comparar_con else "el período anterior"
