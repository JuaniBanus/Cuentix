# Cuentix

**Finanzas personales con IA.** Le contás a un bot de Telegram lo que gastaste —por texto o por audio— y Cuentix lo registra, lo categoriza y te lo devuelve ordenado en una web.

🌐 **En producción:** [cuentix.com.ar](https://cuentix.com.ar)

---

## Qué hace

**Bot de Telegram**
- Registra gastos e ingresos escritos en lenguaje natural ("ayer 4500 de nafta con la Visa") y los interpreta con Google Gemini.
- Transcribe los audios de Telegram y los procesa igual que un mensaje escrito.
- Corrige movimientos ya guardados con texto libre ("no, eran 5000").
- Responde consultas sobre tus gastos en castellano.
- **¿Me lo puedo comprar?**: analiza una compra antes de hacerla.
- **¿Cuotas o contado?**: compara las dos formas de pago contra tasas de referencia.
- Recordatorio diario y alertas de precio de acciones, CEDEARs e índices.

**Web (PWA instalable)**
- Paneles de gastos por categoría y por medio de pago, patrimonio, ahorros e inversiones.
- Objetivos de ahorro y retos sacados de los propios hábitos.
- **Inflación personal**: cuánto subió tu canasta, no la del INDEC.
- Gastos recurrentes, rendimientos de billeteras virtuales y cotización del dólar.
- Narrativa mensual: un resumen en prosa de cómo fue el mes.
- Multiusuario con roles (usuario y superusuario administrador).

## Arquitectura

```
Telegram ──webhook──▶ FastAPI (Render) ──▶ Gemini (parser, transcripción, narrativa)
                            │
                            ▼
                     Supabase (Postgres + RLS)
                            ▲
PWA (Hostinger) ────────────┘
GitHub Actions ──cron──▶ alertas de precio · recordatorio diario · rendimientos
```

- **Backend:** Python 3, FastAPI, Pydantic, httpx.
- **IA:** Google Gemini (`google-genai`) para interpretar texto, transcribir audio y redactar resúmenes. El modelo solo puede elegir categorías de un vocabulario cerrado.
- **Datos:** Supabase (Postgres) con Row Level Security y 22 migraciones versionadas.
- **Frontend:** PWA en JavaScript sin framework, con service worker e íconos instalables.
- **Tareas programadas:** GitHub Actions dispara alertas, recordatorios y actualización de tasas.
- **Seguridad:** secretos solo por variables de entorno, webhook con secreto, límite de pedidos por cliente y cupo diario de APIs externas.

## Correr en local

```bash
pip install -r requirements.txt
cp .env.example .env   # completar TELEGRAM_TOKEN, GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY...
uvicorn app.main:app --reload
```

Las variables que necesita el servicio están documentadas en [`render.yaml`](render.yaml).

## Autor

**Juan Ignacio Banús** — AI Engineer & Abogado · [LinkedIn](https://www.linkedin.com/in/juan-ignacio-banus/) · [GitHub](https://github.com/JuaniBanus)
