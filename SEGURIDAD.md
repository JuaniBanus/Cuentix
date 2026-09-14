# Seguridad de Cuentix

Qué protege cada cosa, y los tres pasos manuales que el código no puede dar solo.

## Los tres modos de acceso, y qué garantiza cada uno

| Superficie | Cómo se autoriza | Qué protege |
|---|---|---|
| `/webhook` | Secreto compartido con Telegram, en cabecera | Que nadie más le mande updates falsos al bot |
| `/tareas/*` | `ALERTAS_SECRET` en cabecera `Authorization` | Que nadie dispare los cron a voluntad |
| `/insights`, `/narrativa`, `/api/*` | Sesión de Supabase | La **cuota** de Gemini y del proveedor de precios |
| Datos de cada usuario | RLS en Postgres + `user_id` en cada consulta | Que nadie vea la plata de otro |

La distinción de la tercera fila importa y es fácil confundirla: la sesión en
`/insights` **no** autoriza el acceso a los datos. Los números llegan ya
calculados por el navegador, que solo pudo obtenerlos si RLS se los dejó ver.
Lo que hace la sesión es que el cupo sea de los usuarios y no de internet.

## Pasos manuales pendientes

### 1. Registrar el webhook con el secreto en cabecera

Hasta que se haga, el bot sigue funcionando por la ruta vieja
(`/webhook/<secreto>`), que deja el secreto escrito en el log de accesos de
Render en cada mensaje. El servidor avisa una vez por arranque mientras siga así.

```sh
curl -X POST "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
        "url": "https://cuentix-bot.onrender.com/webhook",
        "secret_token": "<WEBHOOK_SECRET>",
        "drop_pending_updates": false
      }'
```

Comprobar que quedó bien:

```sh
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/getWebhookInfo"
```

La `url` tiene que terminar en `/webhook`, sin el secreto colgando. Cuando el
log deje de mostrar el aviso, se puede borrar la ruta `/webhook/{secret}` de
`app/main.py`.

**No pongas el token ni el secreto en un archivo del repo.** Estos comandos se
ejecutan una vez, a mano, en tu terminal.

### 2. Variables de entorno en Render

El `.env` local no viaja al servidor. En Render → *Environment*:

| Variable | Valor |
|---|---|
| `ORIGENES_WEB` | `https://cuentix.com.ar,https://www.cuentix.com.ar` |

Las dos formas porque para el navegador `cuentix.com.ar` y `www.cuentix.com.ar`
son orígenes **distintos**. Sin esto, el panel de Insights y la narrativa
mensual fallan por CORS desde el dominio real.

### 3. Auditar RLS

`migrations/015_auditar_rls.sql` son cuatro consultas de lectura que no
modifican nada. Correlas en el editor SQL de Supabase y leer los veredictos.

Hace falta un archivo aparte porque probar RLS desde afuera —con la clave anon,
pidiendo cada tabla sin sesión— tiene un punto ciego: **una tabla vacía devuelve
cero filas esté protegida o no**. En la auditoría de agosto de 2026, cinco de
diez tablas estaban vacías y quedaron sin verificar, aunque el resultado
general parecía un aprobado.

## Reglas que no hay que romper

**Gemini genera intención, el código arma la consulta.** `PlanConsulta`
(`app/models.py`) es vocabulario cerrado: enums, enteros con tope y dos campos
de texto libre acotados a 60 caracteres que se aplican con `.eq()` / `.ilike()`.
Si aparece un campo nuevo de texto libre sin tope, o algo que identifique al
usuario, se rompió la garantía.

**Ninguna función de `app/db.py` tiene `user_id` con valor por defecto.** Un
default convierte un olvido en una consulta que devuelve datos de todos.

**La categoría sale de una lista cerrada, y el que la cierra es Python.** El
prompt le pasa a Gemini las categorías del usuario y le pide que elija una,
pero la garantía es `Vocabulario.resolver()` (`app/categorias.py`): lo que no
está en la lista no llega a la base, cae en «otros» y el bot pregunta. Si
alguna vez el valor del modelo se escribe sin pasar por ahí, se rompió.

**`categorias.user_id` no lleva `default auth.uid()`.** Es al revés que en
`movimientos`, y a propósito: el bot escribe con `service_role`, donde
`auth.uid()` es NULL, así que un olvido no crearía una categoría privada sino
una **base, visible para todos los usuarios**. Sin default, el insert falla.

**La clave anon solo lee `categorias`.** La gestión es del bot. Las policies de
insert/update/delete están escritas y son correctas, pero el `grant` de
escritura no se otorgó: habilitar el ABM en la web es agregarlo, no reescribir
las reglas.

**El medio de pago es un enum, no texto libre.** `MedioPago`
(`app/models.py`) tiene cinco valores y la base los repite en un `CHECK`. Son
dos cerrojos sobre el mismo dato: aunque el modelo devuelva cualquier cosa,
pydantic la rechaza antes de la consulta y Postgres antes del insert. Es lo
contrario de la categoría, que sí es abierta y por eso necesita la tabla y
`Vocabulario.resolver()`. Si alguna vez `medio_pago` pasa a ser `str`, hay que
volver a pensar de dónde sale la garantía.

**Editar un movimiento tiene lista blanca, y borrarlo pide confirmación.**
`CAMPOS_EDITABLES` (`app/db.py`) es lo único que un reply puede tocar: fecha,
tipo, monto, moneda, categoría, descripción, comercio y cuenta. `user_id`, `id`
y `objetivo_id` no están, y el filtro se aplica en `actualizar_movimiento()`,
o sea en el último lugar antes de la base, porque lo que se está escribiendo lo
propuso un modelo a partir de texto libre. La categoría vuelve a pasar por
`Vocabulario.resolver()`: corregir no es una puerta de atrás para meter una
etiqueta que no está en la lista. El borrado, que es lo irreversible, se
reconoce con una lista fija de frases (sin Gemini) y siempre abre una pregunta
antes de ejecutarse.

**Toda escritura por reply se acota al dueño con `.eq("user_id", ...)`.** La
referencia de `mensajes_movimiento` guarda el `user_id` además del movimiento, y
`_atender_reply()` compara contra quién escribe antes de tocar nada: un
`message_id` es un número chico y adivinable, así que la referencia sola nunca
alcanza como autorización.

**Un audio no es una vía paralela: es texto que entra por la misma puerta.**
`app/transcripcion.py` solo convierte la voz en la cadena que el usuario habría
escrito; de ahí en adelante sigue el camino de siempre (respuestas fijas,
comandos, vocabulario de categorías, `Vocabulario.resolver()`). Si alguna vez lo
que devuelve el modelo de audio se escribiera en la base sin pasar por el
parser, se rompió la garantía de la lista cerrada. Y lo que se baja de Telegram
tiene tope —`TOPE_SEGUNDOS` y `TOPE_BYTES`, chequeados antes de descargar y otra
vez contra los bytes que llegan—: sin eso, un archivo grande es un pico de
memoria y una factura de Gemini.

**`esc()` cubre los cinco caracteres** (`& < > " '`), porque se usa tanto en
texto como dentro de atributos. Quitar cualquiera abre XSS por atributo.

**Las claves nunca van al front.** `TWELVE_DATA_API_KEY` y la `service_role` de
Supabase viven solo en el servidor: para eso existe el proxy de `app/mercado.py`.
La única clave que sí es pública es la `anon` de Supabase, y solo es segura
porque RLS la respalda.

## Cómo volver a auditar

`.claude/skills/auditoria-cuentix/SKILL.md` tiene el método completo, adaptado
de las skills de Trail of Bits. Incluye las racionalizaciones que hacen fallar
esta auditoría en particular — entre ellas dar RLS por buena con tablas vacías.
