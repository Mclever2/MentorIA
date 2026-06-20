# Tasks — MentorIA (estadio actual): productización

> Descomposición ejecutable del [plan](./plan.md). Marca el estado real al implementar.
> `[x]` = hecho · `[~]` = parcial / en curso · `[ ]` = pendiente.

## Fase 0 — Andamiaje de producto
- [x] T0.1 Proyecto FastAPI (`api/`) + frontend React (`web/`).
- [x] T0.2 CORS configurable + `lifespan` con precalentamiento (`PRELOAD_ON_STARTUP`).
- [x] T0.3 `registry.py`: almacenamiento en memoria de docs/runs + `RUN_EXCLUSIVO`.

## Fase 1 — Autenticación y multi-tenant
- [x] T1.1 `auth.py` → `usuario_actual` (dependencia).
- [x] T1.2 Propiedad por `user_id` en documentos y runs (404 a terceros).

## Fase 2 — Documentos
- [x] T2.1 `POST /api/documentos`: extracción sin índice + vectorización + TOC + stats.
- [x] T2.2 Dedupe por hash MD5 (reutiliza indexado en memoria).
- [x] T2.3 Validación de PDF escaneado (422).
- [x] T2.4 Rehidratación de memoria + reaplicación de snapshot (rúbrica/perfil).

## Fase 3 — Rúbrica dinámica
- [x] T3.1 `rubrica_service.py`: `procesar_rubrica` + `mapear_rubrica` + `RubricaInvalida`.
- [x] T3.2 `POST /api/documentos/{id}/rubrica` (devuelve `mapa_secciones`).
- [x] T3.3 `POST /api/documentos/{id}/recursos` (sync sin re-indexar).
- [x] T3.4 Snapshot de rúbrica por chat + nodo `_rubrica.py` en el grafo.

## Fase 4 — Perfil de universidad
- [x] T4.1 `reglamento_service.py` + `backend/mcp/web_search.py` (búsqueda web).
- [x] T4.2 `POST /api/universidad/buscar` (con `encontrado:false` y fallback manual).
- [x] T4.3 `POST /api/universidad/subir` (PDF/.docx → perfil destilado).

## Fase 5 — Chat e intención
- [x] T5.1 `intent.py`: `interpretar_mensaje` → `conversacion | secciones | completo`.
- [x] T5.2 `conversador.py`: respuesta anclada en documento + biblioteca.
- [x] T5.3 Confirmaciones: re-evaluar sección ya evaluada / aplicar mejoras pendientes.
- [x] T5.4 Creación de run (`max_iteraciones` acotado a 1–3).

## Fase 6 — Ejecución y streaming
- [x] T6.1 `grafo.py`: `construir_estado_inicial`, `ejecutar_seccion`, `informe_secciones_md`.
- [x] T6.2 `full_review.py`: `ejecutar_revision_completa` (modo completo).
- [x] T6.3 `GET /api/runs/{id}/stream` (SSE) con `RUN_EXCLUSIVO` + encolado.
- [x] T6.4 `POST /api/runs/{id}/cancelar` + evento `cancelado` limpio.
- [x] T6.5 `mejoras.py`: pendientes / aplicar / registrar / restaurar (memoria, no PDF).

## Fase 7 — Tipos de investigación y evaluación
- [~] T7.1 Detección de tipo (cuanti/cuali/mixta/tecnológica/innovación) vía RAG y adaptación de agentes.
- [~] T7.2 Juez LLM solo inicial/final (gain score); Auditor = nota oficial.

## Fase 8 — Despliegue
- [x] T8.1 `cloudbuild.yaml` + `.gcloudignore` (raíz y `web/`).
- [x] T8.2 Cloud Run `min-instances=1` + cliente httpx compartido.
- [x] T8.3 `DEPLOY.md`.

## Fase 9 — Compatibilidad
- [x] T9.1 `POST /evaluar` legacy síncrono.

## Pendiente / backlog (trabajo futuro de la spec §8)
- [ ] T10.1 Persistencia duradera (BD/Supabase) de documentos/runs/historial.
- [ ] T10.2 Concurrencia de varios runs por instancia / estado externo para escalar.
- [ ] T10.3 Exportación consolidada del proyecto + comparativa entre versiones.

## Verificación (mapeo a criterios de aceptación)
- [x] V1 PDF nativo → TOC+stats; escaneo → 422. *(CA-01)*
- [x] V2 Rúbrica → `mapa_secciones`. *(CA-02)*
- [x] V3 Intención correcta (secciones vs conversación). *(CA-03)*
- [x] V4 Confirmaciones de re-evaluación / mejoras. *(CA-04)*
- [x] V5 SSE ordenado + cancelación. *(CA-05)*
- [x] V6 Aislamiento entre usuarios. *(CA-06)*
- [x] V7 Segundo run encolado. *(CA-07)*
- [x] V8 Mejoras solo en memoria RAG. *(CA-08)*
