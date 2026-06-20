# Tasks — POC #3: Red multiagente pura en LangGraph

> Descomposición ejecutable del [plan](./plan.md). Estado retrospectivo: completadas.

## Fase 0 — Andamiaje
- [x] T0.1 Estructura `backend/graph/{nodes,edges,state,workflow}` + `evaluator/` + `context/`.
- [x] T0.2 Dependencias: langgraph, langchain-openai, httpx, chromadb, sentence-transformers, rouge-score.
- [x] T0.3 Cliente `httpx` único compartido + saneo de `OPENAI_API_KEY` (strip de `\r\n`).

## Fase 1 — Estado y routing
- [x] T1.1 `state.py`: `MentoriaState` (TypedDict) con todos los campos por dominio.
- [x] T1.2 `edges.py`: `routing_supervisor` + `DESTINOS_VALIDOS` (lee `siguiente_nodo`, fallback `fin`).

## Fase 2 — Supervisor (corazón de la red)
- [x] T2.1 `make_nodo_supervisor`: invocación LLM con estado resumido.
- [x] T2.2 `_validar_decision_semantica` (invariantes por destino).
- [x] T2.3 `_fallback_routing` determinista.
- [x] T2.4 Anti-bucle capa semántica (`pasos >= max_pasos_red`) + terminación determinista (ciclo completo + auditado).
- [x] T2.5 Reset de flags al enrutar a `redactor`.

## Fase 3 — Nodos trabajadores
- [x] T3.1 `auditor.py` (rúbrica → `errores_rubrica`, `puntaje_estimado`, subagentes).
- [x] T3.2 `metodologico.py` (rigor + coherencia cruzada).
- [x] T3.3 `redactor.py` (reescritura, `numero_iteracion++`, historial de textos).
- [x] T3.4 `consenso.py` + `disenso.py`.
- [x] T3.5 `debate.py` (panel con memoria compartida intra-nodo + sintetizador).
- [x] T3.6 `exportador.py` (serializa estado → `run_*.json`, `debate_*.md`, sin LLM).
- [x] T3.7 Helpers `_rag_planner.py`, `_panel_utils.py`, `_utils.py` (prompt loader, backoff).
- [x] T3.8 Prompts `.md` (supervisor_red, auditor, metodológico, redactor, debate_*, consenso, disenso).

## Fase 4 — Compilación del grafo
- [x] T4.1 `workflow.py`: `create_graph` (nodos + entry point + conditional edge + edges de retorno).
- [x] T4.2 LLM por agente (temperatura por rol) sobre el cliente httpx compartido.
- [x] T4.3 `MemorySaver` + `get_run_config(thread_id)` con `recursion_limit=80`.

## Fase 5 — RAG y contexto
- [x] T5.1 `backend/rag/*` (embeddings, vector_store, library/tesis store, rubric_parser, rag_context).
- [x] T5.2 `context/loaders/*` (local/GCS/GDrive).

## Fase 6 — Evaluador
- [x] T6.1 `metrics/{gain_score,cosine_sim,context_precision,kappa,llm_judge,rouge_bleu}.py`.
- [x] T6.2 `evaluator.py` (`evaluar_desde_archivo`) + `report.py` → `eval_*.json`.

## Fase 7 — Interfaces
- [x] T7.1 Frontend Streamlit (`frontend/`).
- [x] T7.2 API mínima legacy (`api/main.py`).

## Verificación (mapeo a criterios de aceptación)
- [x] V1 Nunca excede `max_pasos_red`/`recursion_limit`; decisión inválida → fallback. *(CA-01)*
- [x] V2 Invariantes de `consenso`/`disenso`/`fin` respetadas. *(CA-02)*
- [x] V3 Terminación exacta: iter completas + texto + auditado. *(CA-03)*
- [x] V4 Artefactos `run_*.json` / `debate_*.md` / `eval_*.json` en disco. *(CA-04)*
- [x] V5 Gain score inicial→final calculado. *(CA-05)*
