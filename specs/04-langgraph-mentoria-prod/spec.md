# Spec — MentorIA (estadio actual): productización LangGraph + FastAPI + React

- **ID**: 04-langgraph-mentoria-prod
- **Estado**: **Vivo** (en desarrollo activo — este repositorio)
- **Origen**: evoluciona el POC #3 (`langgraph-red`) hacia un producto desplegable
- **Constitución aplicable**: todos los principios (P1–P10) y las restricciones del §5

## 1. Resumen

Convierte la red multiagente del POC #3 en un **producto web multiusuario**: una **API
FastAPI** con **chat conversacional** (detección de intención), **streaming SSE** del
progreso de los agentes, **runs cancelables**, gestión de **documentos / rúbrica
dinámica / perfil de universidad** por sesión, y un **frontend React**. Despliegue en
**Cloud Run**. El núcleo de razonamiento sigue siendo el grafo LangGraph de red pura.

## 2. Objetivo y no-objetivos

**Objetivo**: que un mentor converse con el sistema en lenguaje natural, suba su proyecto
y su rúbrica, defina la universidad, dispare evaluaciones por sección o completas, vea el
avance en vivo y reciba texto mejorado — todo en una web desplegada.

**No-objetivos del estadio actual** (restricciones conscientes, ver §5):
- Persistencia duradera del estado de runs/documentos entre reinicios de instancia.
- Concurrencia de múltiples runs simultáneos por instancia.

## 3. Usuarios y casos de uso

- **Estudiante/Mentor autenticado** que mantiene una conversación-asesoría sobre su tesis.

Flujo:
1. Sube el PDF del proyecto (se vectoriza; se detecta el TOC y estadísticas de secciones).
2. Opcionalmente sube una **rúbrica** (PDF) y define su **universidad** (búsqueda
   automática de reglamento o subida manual → perfil institucional).
3. **Conversa**: pregunta dudas, o pide "evalúa el Planteamiento" / "revisa todo".
4. El sistema detecta la **intención**, confirma cuando hace falta y lanza un **run**.
5. Ve el **progreso en vivo** (qué agente actúa) y puede **cancelar**.
6. Recibe informe + texto mejorado; decide si incorpora las mejoras a la memoria.

## 4. Requisitos funcionales

### 4.1 Gestión de documentos
- **RF-01 — Subida y vectorización.** `POST /api/documentos` extrae texto omitiendo el
  índice, vectoriza, detecta `estructura_toc` y `stats` de secciones. Rechaza PDFs
  escaneados sin texto (422).
- **RF-02 — Deduplicación.** Se identifica el PDF por hash MD5; re-subir el mismo
  documento reutiliza el ya indexado en memoria.
- **RF-03 — Rehidratación.** Al reabrir un chat se puede reconstruir la memoria
  (secciones evaluadas + texto corregido) y reaplicar el snapshot de rúbrica/perfil.

### 4.2 Rúbrica dinámica
- **RF-04 — Subida de rúbrica.** `POST /api/documentos/{id}/rubrica` parsea, valida y
  **mapea la rúbrica a las secciones reales** del proyecto (`mapa_secciones`).
- **RF-05 — Snapshot por chat.** La rúbrica (ya mapeada) y el perfil de universidad se
  guardan como snapshot de la sesión para no reprocesar; sincronizables sin re-indexar el
  PDF (`POST /api/documentos/{id}/recursos`).

### 4.3 Perfil de universidad
- **RF-06 — Búsqueda de reglamento.** `POST /api/universidad/buscar` busca reglamentos
  (web) y destila un **perfil institucional**; si no encuentra material útil, devuelve
  `encontrado:false` para ofrecer subida manual.
- **RF-07 — Subida de reglamento.** `POST /api/universidad/subir` destila el perfil desde
  un PDF/.docx subido. El perfil ajusta la "personalidad" y criterios por universidad.

### 4.4 Chat e intención
- **RF-08 — Detección de intención.** `POST /api/chat` clasifica el mensaje en
  `conversacion` | `secciones` (lista de secciones objetivo) | `completo`.
- **RF-09 — Conversación.** Si es consulta, responde con un conversador apoyado en el
  documento y la biblioteca (sin lanzar la red de agentes).
- **RF-10 — Confirmaciones.** Antes de evaluar pide confirmación cuando: (a) la sección
  **ya fue evaluada** (re-evaluar), o (b) hay **mejoras pendientes** de otras secciones
  sin incorporar a la memoria.
- **RF-11 — Creación de run.** Si procede, registra un run (`modo`, `secciones`,
  `max_iteraciones` acotado a 1–3) y devuelve su `run_id`.

### 4.5 Ejecución y streaming
- **RF-12 — Streaming SSE.** `GET /api/runs/{id}/stream` emite eventos del progreso
  (`inicio`, `fase`, `seccion_completada`, `resultado`, `cancelado`, `error`, `fin`).
- **RF-13 — Modo completo vs por secciones.** `completo` ejecuta la revisión integral;
  `secciones` itera sección por sección (un `thread_id` por sección) y consolida un
  informe en Markdown.
- **RF-14 — Cancelación.** `POST /api/runs/{id}/cancelar` señala el evento de cancelación;
  el stream emite `cancelado` y se detiene de forma limpia.
- **RF-15 — Mejoras a la memoria (no al PDF).** El texto corregido se acumula como
  "mejora pendiente"; el usuario decide incorporarlo a la **memoria RAG** — nunca al PDF.

### 4.6 Tipos de investigación y evaluación
- **RF-16 — Tipo de investigación.** El sistema detecta el tipo (cuantitativa /
  cualitativa / mixta / tecnológica / innovación) vía RAG y adapta a todos los agentes;
  el juez usa la rúbrica adecuada al tipo.
- **RF-17 — Juez vs rúbrica.** El juez LLM evalúa solo inicial/final (gain score); la
  iteración y la trayectoria las gobiernan la rúbrica/red; el Auditor es la **nota
  oficial**.

### 4.7 Seguridad y multi-tenant
- **RF-18 — Autenticación.** Todos los endpoints de datos requieren usuario; cada
  documento/run pertenece a un `user_id` y solo su dueño accede (404 en caso contrario).

### 4.8 Compatibilidad
- **RF-19 — Endpoint legacy.** `POST /evaluar` mantiene la evaluación síncrona de una
  sección (PDF completo como contexto, sin RAG ni streaming) por compatibilidad.

## 5. Requisitos no funcionales

- **RNF-01 — Despliegue.** Cloud Run con `min-instances=1`; build vía `cloudbuild.yaml`.
- **RNF-02 — Estado en memoria.** Vector store y `registry` de documentos/runs viven en
  el proceso; no hay persistencia entre reinicios (al reiniciar, el usuario re-sube).
- **RNF-03 — Un run por instancia.** Lock exclusivo (`RUN_EXCLUSIVO`): si llega otro run,
  se encola y el stream avisa "esperando…".
- **RNF-04 — CORS configurable.** `ALLOWED_ORIGINS` por entorno.
- **RNF-05 — Precalentamiento.** En `startup`, si `PRELOAD_ON_STARTUP=1`, se precalientan
  embeddings/biblioteca (degradación lazy si falla).
- **RNF-06 — Resiliencia.** Hereda del POC #3: anti-bucle en dos capas, fallback de
  routing, backoff y cliente httpx compartido (clave en Cloud Run).
- **RNF-07 — Entorno local.** Usar `venv\Scripts\python.exe`.

## 6. Criterios de aceptación

- **CA-01**: Subir un PDF nativo devuelve `estructura_toc` + `stats`; un escaneo sin texto
  devuelve 422 con mensaje accionable. *(RF-01)*
- **CA-02**: Subir una rúbrica devuelve `mapa_secciones` con el nº de secciones mapeadas a
  las del proyecto. *(RF-04)*
- **CA-03**: "evalúa el Planteamiento" crea un run en modo `secciones=["Planteamiento…"]`;
  una pregunta general responde en modo `conversacion` sin lanzar agentes. *(RF-08, RF-09)*
- **CA-04**: Re-evaluar una sección ya evaluada, o evaluar con mejoras pendientes en otras
  secciones, pide confirmación antes de proceder. *(RF-10)*
- **CA-05**: El stream emite eventos ordenados hasta `fin`; `POST .../cancelar` produce un
  evento `cancelado` y corta el stream. *(RF-12, RF-14)*
- **CA-06**: Un usuario no puede acceder a documentos/runs de otro (404). *(RF-18)*
- **CA-07**: Con un run en curso, un segundo run se encola (no corre en paralelo). *(RNF-03)*
- **CA-08**: Incorporar mejoras cambia solo la memoria RAG; el PDF original queda intacto.
  *(RF-15, P7)*

## 7. Métrica de éxito

Un mentor completa el ciclo **subir → conversar → evaluar → ver progreso → recibir texto
mejorado** desde la web desplegada, con la rúbrica y universidad correctas aplicadas, sin
intervención manual en el servidor.

## 8. Trabajo futuro (fuera de alcance actual)

- Persistencia duradera (BD/Supabase) de documentos, runs e historial entre reinicios.
- Concurrencia real de varios runs por instancia / escalado horizontal con estado externo.
- Exportación del proyecto consolidado y comparativas entre versiones.
