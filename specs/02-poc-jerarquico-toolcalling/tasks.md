# Tasks — POC #2: Jerarquía real con tool-calling + RAG

> Descomposición ejecutable del [plan](./plan.md). Estado retrospectivo: completadas.

## Fase 0 — Andamiaje
- [x] T0.1 Estructura `backend/{agents,prompts,rag}` + `frontend/{components}` + `books/`.
- [x] T0.2 `requirements.txt` (swarms, chromadb, langchain-chroma, sentence-transformers, pdfplumber, streamlit, pydantic).
- [x] T0.3 Silenciado de logs (`LITELLM_LOG`, `SWARMS_VERBOSE`) + claves por agente.

## Fase 1 — Configuración de dominio (fuente de verdad)
- [x] T1.1 `RUBRICA_ITEMS_UPAO` (33 ítems) + `SECCIONES` (mapeo sección→ítems).
- [x] T1.2 `CROSS_DEPS` (grafo de dependencias) + `CROSS_QUERIES` + `SECTION_QUERIES`.
- [x] T1.3 `SCORE_TABLE` + `puntaje_a_nota`.

## Fase 2 — RAG
- [x] T2.1 `embeddings.py` (MiniLM-L6-v2, CPU, L2).
- [x] T2.2 `extractor.py` (PDF → secciones).
- [x] T2.3 `library_store.py` persistente + precarga desde `/books` (800/100).
- [x] T2.4 `tesis_store.py` efímero + `query_context` / `query_cross_context` (600/80).
- [x] T2.5 `rubric_parser.py`.

## Fase 3 — Sub-agentes
- [x] T3.1 `auditor.py` (`ReporteAuditor`, `items_evaluados`, `aprobado`).
- [x] T3.2 `metodologico.py` (coherencia + dependencias cruzadas).
- [x] T3.3 `redactor.py` (texto mejorado + argumento).
- [x] T3.4 Prompts `.md` (director jerárquico, auditor, metodológico, redactor, debate, consenso, disenso).
- [x] T3.5 `utils.py` (`run_agent_silently`, `extract_json`, `call_with_backoff`, `use_*_key`).

## Fase 4 — Herramientas y Director
- [x] T4.1 `herramientas.py`: fábrica de tools atómicas con contexto por closure + `state` compartido.
- [x] T4.2 `director.py`: `_build_director_con_herramientas` (`max_loops=20`).
- [x] T4.3 Tarea inicial breve (el contexto RAG vive en las closures).
- [x] T4.4 **Fallbacks garantizados** post-run: Redactor, revisión, Consenso, Disenso.
- [x] T4.5 Veredicto de fallback si falta el bloque "VEREDICTO DIRECTOR".
- [x] T4.6 Limpieza/inicialización de `agent_workspace`.
- [x] T4.7 `progress_cb` para fases visibles en la UI.

## Fase 5 — Frontend (4 pantallas)
- [x] T5.1 `app.py` router + `resources.py` (singletons `@st.cache_resource`) + `session_manager.py`.
- [x] T5.2 `sidebar.py` (indexar biblioteca + estado del sistema).
- [x] T5.3 `pantalla_upload.py` → `pantalla_seleccion.py` → `pantalla_revision.py` (HITL) → `pantalla_resultado.py`.
- [x] T5.4 Edición del texto propuesto + re-análisis hasta `MAX_ITERACIONES` + descarga `.txt`/`.json`.

## Verificación (mapeo a criterios de aceptación)
- [x] V1 El orden de agentes lo decide el Director (varía entre secciones). *(CA-01)*
- [x] V2 Observaciones rastreables a contexto RAG (principal + cruzado). *(CA-02)*
- [x] V3 Director omite Redactor → texto entregado por fallback. *(CA-03)*
- [x] V4 Biblioteca persiste; tesis efímera se destruye. *(CA-04)*
- [x] V5 Edición + re-análisis hasta el límite. *(CA-05)*
- [x] V6 Todos los ítems ≥ 2 ⇒ Aprobado. *(CA-06)*
