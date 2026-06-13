# Guía de despliegue — MentorIA (React + FastAPI + Supabase en Cloud Run)

Arquitectura de 3 piezas separadas:

```
┌──────────────────┐  HTTPS / SSE   ┌─────────────────────────┐
│ mentoria-web      │ ─────────────▶ │ mentoria-api             │
│ Cloud Run (nginx) │                │ Cloud Run (FastAPI)      │
│ React estático    │ ◀───────────── │ LangGraph + Chroma + RAG │
└────────┬─────────┘   progreso      └────────────┬────────────┘
         │                                        │ (verifica JWT)
         └──────────────┬─────────────────────────┘
                        ▼
              ┌───────────────────┐
              │ Supabase (gratis)  │  Auth + Postgres (historial)
              └───────────────────┘
```

---

## Parte 1 — Supabase (15 min, una sola vez)

1. Entra a [supabase.com](https://supabase.com) → **New project**.
   - Name: `mentoria` · Database password: guárdala · Region: `South America (São Paulo)`.
2. **Crear las tablas**: Dashboard → **SQL Editor** → New query → pega el contenido
   completo de [`supabase/schema.sql`](supabase/schema.sql) → **Run**.
   Esto crea `conversaciones` y `mensajes` con Row Level Security (cada usuario solo ve lo suyo).
2b. **Persistencia de sesión por chat**: ejecuta TAMBIÉN [`supabase/schema_v2.sql`](supabase/schema_v2.sql).
   Añade las columnas del documento a `conversaciones`, crea el bucket privado **`tesis`** (donde se
   guarda el PDF de cada chat) y sus políticas RLS. Sin esto, el chat no recuerda el proyecto al reabrirlo.
3. **Copiar las 3 credenciales** (Dashboard → **Project Settings → API**):
   - `Project URL` → será `VITE_SUPABASE_URL` (frontend)
   - `anon public` key → será `VITE_SUPABASE_ANON_KEY` (frontend)
   - `JWT Secret` (sección *JWT Settings*) → será `SUPABASE_JWT_SECRET` (backend)
4. (Opcional) **Desactivar confirmación por correo** para probar más rápido:
   Authentication → Providers → Email → desmarca *Confirm email*.

---

## Parte 2 — Backend en Cloud Run (`mentoria-api`)

El `Dockerfile` de la raíz ya quedó configurado para FastAPI (`uvicorn api.main:app`).

```bash
# 1. Variables del proyecto
gcloud config set project TU_PROYECTO_GCP
export REGION=us-central1

# 2. Construir la imagen (igual que antes con Streamlit)
gcloud builds submit --tag gcr.io/TU_PROYECTO_GCP/mentoria-api .

# 3. Desplegar — min-instances=1 elimina el arranque en frío
gcloud run deploy mentoria-api \
  --image gcr.io/TU_PROYECTO_GCP/mentoria-api \
  --region $REGION \
  --memory 4Gi --cpu 2 \
  --min-instances 1 --max-instances 2 \
  --concurrency 8 \
  --timeout 1800 \
  --cpu-boost \
  --allow-unauthenticated \
  --set-env-vars "OPENAI_API_KEY=sk-...,SUPABASE_JWT_SECRET=TU_JWT_SECRET,ALLOWED_ORIGINS=*,PRELOAD_ON_STARTUP=1"
```

Notas importantes:
- `--timeout 1800` (30 min): el stream SSE de una revisión profunda puede durar >10 min.
- `--memory 4Gi`: el modelo de embeddings + Chroma + el grafo necesitan holgura.
- `OPENAI_API_KEY` idealmente via Secret Manager:
  `--set-secrets "OPENAI_API_KEY=openai-key:latest"` en lugar de `--set-env-vars`.
- Apunta la URL que devuelve el deploy (ej. `https://mentoria-api-xxxxx-uc.a.run.app`).
- Después de desplegar el frontend, vuelve a desplegar con
  `ALLOWED_ORIGINS=https://mentoria-web-xxxxx-uc.a.run.app` (CORS restringido).

---

## Parte 3 — Frontend en Cloud Run (`mentoria-web`)

Las variables `VITE_*` se inyectan **en build-time** (quedan dentro del bundle):

```bash
cd web

gcloud builds submit --tag gcr.io/TU_PROYECTO_GCP/mentoria-web \
  --substitutions=_X=1 . \
  # si usas Docker local en su lugar:
  # docker build -t gcr.io/TU_PROYECTO_GCP/mentoria-web \
  #   --build-arg VITE_API_URL=https://mentoria-api-xxxxx-uc.a.run.app \
  #   --build-arg VITE_SUPABASE_URL=https://xxxxx.supabase.co \
  #   --build-arg VITE_SUPABASE_ANON_KEY=eyJ... .
```

Con `gcloud builds submit` los build-args se pasan con un `cloudbuild.yaml` mínimo
(o usa Docker local + `docker push`). El más simple — Docker local:

```bash
gcloud auth configure-docker
docker build -t gcr.io/TU_PROYECTO_GCP/mentoria-web \
  --build-arg VITE_API_URL=https://mentoria-api-xxxxx-uc.a.run.app \
  --build-arg VITE_SUPABASE_URL=https://xxxxx.supabase.co \
  --build-arg VITE_SUPABASE_ANON_KEY=eyJ... \
  ./web
docker push gcr.io/TU_PROYECTO_GCP/mentoria-web

gcloud run deploy mentoria-web \
  --image gcr.io/TU_PROYECTO_GCP/mentoria-web \
  --region $REGION \
  --memory 256Mi --cpu 1 \
  --min-instances 0 \
  --allow-unauthenticated
```

`min-instances=0` aquí está bien: la imagen nginx arranca en <1 segundo.

---

## Parte 4 — Cerrar el círculo

1. Copia la URL del frontend (`https://mentoria-web-xxxxx-uc.a.run.app`).
2. Re-despliega el backend con CORS restringido:
   ```bash
   gcloud run services update mentoria-api --region $REGION \
     --update-env-vars "ALLOWED_ORIGINS=https://mentoria-web-xxxxx-uc.a.run.app"
   ```
3. En Supabase: Authentication → **URL Configuration** → Site URL = URL del frontend.
4. Prueba: landing → registro → subir PDF → «revisa mis objetivos».

---

## Desarrollo local

```bash
# Terminal 1 — backend (usa .env de la raíz; sin SUPABASE_JWT_SECRET corre sin auth)
venv\Scripts\python -m uvicorn api.main:app --port 8080 --reload

# Terminal 2 — frontend (proxy /api → :8080 ya configurado en vite.config.ts)
cd web
copy .env.example .env   # rellena VITE_SUPABASE_* o déjalo vacío (modo invitado)
npm install
npm run dev              # http://localhost:5173
```

Sin `VITE_SUPABASE_URL` el frontend entra en **modo invitado**: salta el login y
no persiste historial — útil para probar los agentes localmente.

---

## Costos estimados

| Pieza | Config | Costo/mes aprox. |
|---|---|---|
| mentoria-api | min-instances=1, 2 vCPU/4Gi (idle sin CPU) | $5–15 |
| mentoria-web | nginx 256Mi, min-instances=0 | ~$0 |
| Supabase | plan Free (500MB DB, 50k usuarios) | $0 |
| OpenAI | gpt-4o-mini por revisión | $0.01–0.05 c/u |
