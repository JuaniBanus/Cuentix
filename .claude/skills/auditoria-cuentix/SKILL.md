---
name: auditoria-cuentix
description: Auditoría de seguridad de Cuentix (FastAPI + Gemini + Supabase + PWA vanilla). Verifica aislamiento entre cuentas, RLS real contra la clave pública, escapado de HTML, el límite entre el LLM y la base, higiene de secretos y superficie de abuso de cuota. Usar antes de publicar cambios, al sumar un endpoint o una tabla, o cuando se pida revisar la seguridad del proyecto.
allowed-tools: Read Grep Glob Bash Write
---

# Auditoría de seguridad de Cuentix

Adaptación de la metodología de las skills de Trail of Bits
(`entry-point-analyzer`, `audit-context-building`, `fp-check`,
`supply-chain-risk-auditor`) a este stack. Las originales suponen contratos
inteligentes; acá los puntos de entrada son endpoints HTTP, mensajes de
Telegram y el navegador hablando directo con Postgres.

## Cuándo usarla

- Antes de publicar cambios en `web/` o desplegar el bot.
- Al agregar un endpoint, una tabla de Supabase o una función de `app/db.py`.
- Cuando se pida "revisá la seguridad" o "auditá el proyecto".

## Cuándo NO usarla

- Para revisar estilo, rendimiento o correctitud funcional.
- Para escribir exploits. Esto reporta y verifica; no ataca.

## Racionalizaciones a rechazar

Cada una llevó a un hallazgo perdido o a un falso positivo en auditorías reales
de este proyecto.

**1. "La función recibe `user_id`, entonces filtra por `user_id`."**
Falso. Recibir el parámetro y no aplicarlo compila, pasa los tests y devuelve
datos de todos los usuarios. Hay que mirar el CUERPO, y seguir la delegación
hasta el `.eq()` concreto.

**2. "La tabla devolvió 0 filas a la clave anon, entonces RLS funciona."**
Falso si la tabla está vacía. Un 0 solo prueba algo cuando la clave de servicio
ve filas y la anon no. Contar filas primero; si está vacía, decir que el
control quedó SIN VERIFICAR en vez de darlo por bueno.

**3. "El valor está escapado donde se arma, así que es seguro."**
Irrelevante: importa dónde se INSERTA. Y al revés — armar sin escapar es
correcto si el escapado ocurre en la interpolación final. Verificar el punto
de inserción, no el de construcción.

**4. "`git log -S` no encontró la clave, entonces no se filtró."**
Depende del patrón. Un regex que exige un carácter alfanumérico tras el prefijo
no matchea un placeholder terminado en puntos, y un prefijo suelto matchea
comentarios de documentación. Comparar por HASH contra la clave viva, nunca por
presencia del prefijo.

**5. "Es una app personal, un DoS no importa."**
La cuota de Gemini y las 700 llamadas diarias del proveedor de precios son
compartidas y agotables por un anónimo. Agotarlas no rompe el servidor: hace
que el dueño vea pantallas vacías sin saber por qué.

## Método

Correr en este orden. Cada paso depende del anterior.

### 1. Mapa de puntos de entrada

Tres superficies, no una:

```sh
grep -rn '@app\.\(get\|post\|put\|delete\)' app/       # HTTP
grep -rn 'def _es_comando\|respuesta_directa' app/     # comandos de Telegram
grep -rhno 'from("[a-z_]*")' web/js/                   # tablas que toca el navegador
```

Clasificar cada uno: sin autenticación, con secreto en la URL, con sesión de
Supabase, o vía `usuarios_telegram`. Lo que no encaje en ninguna, es hallazgo.

### 2. Aislamiento entre cuentas (lo más caro si falla)

Automatizable con AST. Para cada función de `app/db.py` que recibe `user_id`,
comprobar que exista un `.eq("user_id", ...)` o que escriba la columna. Las que
no, seguirlas hasta la función a la que delegan antes de reportar.

### 3. RLS real, no supuesta

Probar con la clave anon de `web/js/config.js` — es pública, está en el front.
**Solo lectura: nunca insertar filas de prueba en producción.** Contar filas con
la clave de servicio primero, para saber qué ceros prueban algo.

### 4. Escapado en el front

`esc()` debe cubrir `& < > " '` (los cinco: se usa dentro de atributos). Buscar
campos escritos por el usuario —`descripcion`, `comercio`, `nombre`,
`categoria`, `cuenta`, `clave_item`— interpolados en HTML sin pasar por `esc()`.

### 5. El límite entre el LLM y la base

La regla del proyecto es que Gemini produce INTENCIÓN, y el código arma la
consulta. Verificar que se sostiene:

- `PlanConsulta` no debe tener ningún campo que identifique al usuario.
- Sus campos libres (`categoria`, `comercio`) van acotados por `max_length` y
  se aplican con `.eq()` / `.ilike()`, con los comodines de LIKE escapados.
- Si aparece un campo nuevo que sea texto libre sin tope, es hallazgo.

### 6. Secretos y dependencias

```sh
python -m bandit -r app -f json -o bandit.json
python -m pip_audit -r requirements.txt --format json
git check-ignore -v .env
```

Para el historial de git, comparar por hash contra el valor vivo. No imprimir
secretos en ningún output: reportar huella, longitud y veredicto.

### 7. Verificar antes de reportar

Ningún hallazgo se reporta sin trazar el camino completo desde la entrada hasta
el efecto. Si no se puede construir el escenario concreto —qué manda el
atacante, qué obtiene—, es una observación, no un hallazgo, y se etiqueta así.
