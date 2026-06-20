# Plan — MentorIA (estadio actual): productización

> Cómo se implementa la [spec](./spec.md). Reutiliza el grafo del POC #3 como núcleo y
> añade la capa de producto (API, chat, recursos de sesión, despliegue).

## 1. Arquitectura de alto nivel

```
┌────────────┐   HTTPS    ┌──────────────────────────────────────────────┐
│  React     │ ─────────▶ │  FastAPI (api/)                              │
│  (web/)    │  SSE        │   auth · chat/intent · documentos · rúbrica  │
└────────────┘ ◀───────── │   universidad · runs(stream/cancelar)        │
                          │            │                                  │
                          │            ▼                                  │
                          │   registry (docs/runs en memoria, RUN_EXCLUSIVO)
                          │            │                                  │
                          │            ▼                                  │
                          │   grafo LangGraph red pura (backend/graph)    │
                          │   + RAG (backend/rag) + evaluator/            │
                          └──────────────────────────────────────────────┘
                                       │ deploy
                                       ▼
                               Google Cloud Run (min-instances=1)
```

El **núcleo de razonamiento no cambia** respecto al POC #3 (ver
[03-poc-langgraph-red/plan.md](../03-poc-langgraph-red/plan.md)); este estadio añade
**todo lo que lo convierte en producto**.

## 2. Stack tecnológico (capa nueva)

| Componente | Tecnología |
|---|---|
| API | FastAPI (`lifespan`, `StreamingResponse` SSE, `UploadFile`/`Form`) |
| Auth | `api/auth.py` → `usuario_actual` (dependencia FastAPI, `user.sub`) |
| Frontend | React (`web/`) |
| Búsqueda de reglamentos | Web search MCP (`backend/mcp/web_search.py`, p.ej. Tavily) |
| Extracción PDF | pdfplumber (+ extracción sin índice) |
| Despliegue | Cloud Run + `cloudbuild.yaml` + `.gcloudignore` (raíz y `web/`) |
| Núcleo | LangGraph + RAG + evaluator (heredado del POC #3) |

## 3. Superficie de la API (`api/main.py`)

| Método | Ruta | Función |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/biblioteca` | Libros indexados + total de fragmentos |
| POST | `/api/documentos` | Sube PDF, vectoriza, devuelve TOC + stats (+ rehidratación/snapshot) |
| POST | `/api/documentos/{id}/rubrica` | Parsea, valida y mapea la rúbrica a las secciones |
| POST | `/api/documentos/{id}/recursos` | Sincroniza rúbrica/perfil sin re-indexar |
| POST | `/api/universidad/buscar` | Busca reglamento (web) → perfil; `encontrado:false` si nada útil |
| POST | `/api/universidad/subir` | Destila perfil desde reglamento subido (PDF/.docx) |
| POST | `/api/chat` | Detecta intención → conversación, confirmación o creación de run |
| GET | `/api/runs/{id}/stream` | SSE del progreso de los agentes |
| POST | `/api/runs/{id}/cancelar` | Señala cancelación del run |
| POST | `/evaluar` | Legacy síncrono (sin RAG ni streaming) |

## 4. Componentes de la capa de producto (`api/`)

| Módulo | Responsabilidad |
|---|---|
| `main.py` | Definición de endpoints, CORS, lifespan, SSE (`_eventos_run`, `_sse`) |
| `auth.py` | Autenticación → `usuario_actual` |
| `registry.py` | Estado en memoria: documentos y runs por usuario; `RUN_EXCLUSIVO` (lock); dedupe por hash |
| `intent.py` | `interpretar_mensaje` → `{modo, secciones}` |
| `conversador.py` | Respuesta conversacional anclada en documento + biblioteca |
| `grafo.py` | `construir_estado_inicial`, `ejecutar_seccion`, `informe_secciones_md` (puente API↔grafo) |
| `full_review.py` | `ejecutar_revision_completa` (modo completo) |
| `mejoras.py` | Memoria de texto corregido: `pendientes`, `aplicar_pendientes`, `registrar_resultado`, `restaurar_memoria` |
| `rubrica_service.py` | `procesar_rubrica`, `mapear_rubrica`, `RubricaInvalida` |
| `reglamento_service.py` | `perfil_desde_busqueda`, `perfil_desde_documento`, `ReglamentoInvalido` |
| `llm.py`, `deps.py` | Cliente LLM y dependencias cacheadas (`get_embeddings`, `get_biblioteca`, `precalentar`) |
| `backend/graph/nodes/_rubrica.py` | Soporte de rúbrica dinámica dentro del grafo (nuevo vs POC #3) |
| `backend/mcp/web_search.py` | Búsqueda web para reglamentos (nuevo vs POC #3) |

## 5. Decisiones de diseño y trade-offs

- **D1 — Reutilizar el grafo del POC #3 sin tocar su núcleo.** La capa de producto es una
  fachada; el razonamiento queda aislado y testeable. La API traduce entre HTTP/SSE y el
  estado del grafo (`api/grafo.py`).
- **D2 — Chat con intención como puerta de entrada.** Un solo endpoint (`/api/chat`)
  decide entre conversar, confirmar o ejecutar; evita exponer la complejidad del grafo al
  cliente y permite confirmaciones (re-evaluar, aplicar mejoras).
- **D3 — Snapshot de rúbrica/perfil por chat.** La rúbrica mapeada y el perfil de
  universidad se persisten como snapshot de sesión y se reaplican en la rehidratación,
  evitando reprocesar en cada apertura. Modelo *snapshot-por-chat*.
- **D4 — Mejoras a la memoria, nunca al PDF (P7).** `mejoras.py` separa el texto corregido
  como "pendiente"; incorporarlo es decisión explícita y solo afecta la memoria RAG.
- **D5 — Estado en memoria + 1 run por instancia (RNF-02, RNF-03).** Coherente con
  Cloud Run `min-instances=1` y el vector store en RAM: simplifica el MVP a costa de
  durabilidad y concurrencia (ver §8 de la spec: trabajo futuro = persistencia/Supabase).
- **D6 — SSE en threadpool.** `_eventos_run` es un generador síncrono que corre el grafo
  y emite eventos; el lock exclusivo se adquiere/libera alrededor del run, encolando si
  hace falta.
- **D7 — Cliente httpx compartido (heredado).** Imprescindible en Cloud Run para evitar
  fallos intermitentes de conexiones nuevas por cada LLM.

## 6. Configuración (variables de entorno)

| Variable | Default | Uso |
|---|---|---|
| `ALLOWED_ORIGINS` | `*` | CORS |
| `PRELOAD_ON_STARTUP` | `1` | Precalentar embeddings/biblioteca al iniciar |
| `GROQ_API_KEY_*` | — | Claves LLM (rotación en `config.Config.GROQ_KEYS`) |
| `MAX_ITERATIONS` | 3 | Iteraciones (acotado a 1–3 en `/api/chat`) |
| `CONTEXT_SOURCE` / `GCS_BUCKET_NAME` | local / — | Origen de contexto/biblioteca |
| (web search) | — | Clave del proveedor de búsqueda para reglamentos |

## 7. Despliegue

- Build con `cloudbuild.yaml`; `.gcloudignore` en raíz y en `web/`.
- Cloud Run con `min-instances=1` (evita cold start del modelo de embeddings).
- Ver `DEPLOY.md` para el procedimiento completo.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Reinicio de instancia pierde docs/runs | UX de re-subida + rehidratación de memoria (RF-03); persistencia = trabajo futuro |
| Un solo run por instancia limita throughput | Lock + encolado con aviso en el stream; escalado con estado externo = futuro |
| Rate limits LLM | Rotación de claves Groq + backoff + httpx compartido |
| PDF escaneado sin texto | Validación temprana → 422 accionable |
| Mapeo de rúbrica a secciones impreciso | Mapeo contra el TOC real + revisión del nº de secciones mapeadas |
