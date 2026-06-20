# Plan — POC #3: Red multiagente pura en LangGraph

> Cómo se implementa la [spec](./spec.md).

## 1. Patrón arquitectónico

**Red pura sobre `StateGraph`.** Un Supervisor-router es el único nodo con poder de
decisión; el resto son trabajadores que siempre vuelven a él.

```
START → nodo_supervisor ──(conditional edge: lee state["siguiente_nodo"])──┐
            │                                                              │
            ├─→ nodo_redactor ──────────────────────────────────────────┐ │
            ├─→ nodo_auditor ───────────────────────────────────────────┤ │
            ├─→ nodo_metodologico ──────────────────────────────────────┤ │
            ├─→ nodo_debate  (panel de subagentes + memoria compartida) ─┤ │
            ├─→ nodo_consenso ──────────────────────────────────────────┤ │
            ├─→ nodo_disenso ───────────────────────────────────────────┘ │
            └─→ nodo_exportador → END    (cuando siguiente_nodo == "fin")  │
   Todos los nodos trabajadores regresan al Supervisor ───────────────────┘
```

Routing: `add_conditional_edges("nodo_supervisor", routing_supervisor, {...})`.
`routing_supervisor` no tiene lógica: lee `siguiente_nodo` y, si no es válido, devuelve
`fin` (destino seguro). Toda la inteligencia vive en `nodes/supervisor.py`.

## 2. Stack tecnológico

| Componente | Tecnología |
|---|---|
| Orquestación | LangGraph `StateGraph` + `MemorySaver` (checkpointer) |
| LLM | `langchain_openai.ChatOpenAI` (`gpt-4o-mini`, temperatura por rol) |
| Cliente HTTP | `httpx.Client` único compartido (keepalive, timeouts) |
| RAG | embeddings + vector store + library/tesis store + rubric_parser (patrón POC #2) |
| Evaluación | módulo `evaluator/` con métricas (juez LLM, cosine, kappa, ROUGE/BLEU) |
| Frontend | Streamlit (`frontend/`) + API mínima legacy (`api/main.py`) |
| Extras (scaffolding) | `backend/lora/`, `backend/mcp/` (drive connector, tools), `backend/metrics/coherencia.py` |

## 3. Estado del grafo (`backend/graph/state.py`)

`MentoriaState` (TypedDict) es el estado compartido. Campos clave:

- **Entrada/RAG**: `seccion_objetivo`, `contexto_recuperado`, `contexto_dependencias`,
  `contexto_teorico`, `rubrica_dinamica`.
- **Ciclo**: `max_iteraciones`, `numero_iteracion`, `pasos_ejecutados`, `max_pasos_red`.
- **Redactor**: `texto_iterado`, `historial_textos`, `redactor_evaluacion_rubrica`.
- **Auditor**: `feedback_auditor`, `errores_rubrica[]`, `puntaje_estimado`,
  `scores_subagentes`, `consenso_matematico_auditor`.
- **Metodólogo**: `observaciones_metodologicas`.
- **Consenso/Disenso**: `resultado_consenso`, `resultado_disenso`, `iter_*`.
- **Debate**: `debate_memory[]`, `debate_veredicto`, `debate_completado`, `historial_debate`.
- **Routing**: `siguiente_nodo`, `instrucciones_supervisor`, flags `*_ejecutado` por nodo.
- **Identidad/Traza**: `universidad`, `programa`, `modalidad`, `run_id`,
  `puntaje_inicial`, `rutas_reportes`, `evaluacion_upao_inicial/final`.

## 4. Componentes

| Módulo | Responsabilidad |
|---|---|
| `backend/graph/workflow.py` | Construcción/compilación del grafo, LLM por agente, `get_run_config` |
| `backend/graph/edges.py` | `routing_supervisor` (lee `siguiente_nodo`; `DESTINOS_VALIDOS`) |
| `backend/graph/nodes/supervisor.py` | Decisión LLM + validación semántica + fallback determinista + anti-bucle |
| `backend/graph/nodes/{auditor,metodologico,redactor,consenso,disenso}.py` | Nodos trabajadores |
| `backend/graph/nodes/debate.py` | Panel de subagentes con memoria compartida + sintetizador |
| `backend/graph/nodes/exportador.py` | Serializa el estado final (sin LLM) |
| `backend/graph/nodes/_rag_planner.py`, `_panel_utils.py`, `_utils.py` | Helpers (carga de prompt, backoff, RAG) |
| `backend/rag/*` | Embeddings, stores, rubric parser, contexto |
| `evaluator/` | `evaluator.py` + `metrics/{gain_score,cosine_sim,context_precision,kappa,llm_judge,rouge_bleu}.py` + `report.py` |
| `context/` | Loaders (local/GCS/GDrive) para rúbricas/contexto |

## 5. Decisiones de diseño y trade-offs

- **D1 — Red pura, no jerarquía.** *Ventaja*: grafo inspeccionable, checkpoints, una sola
  autoridad de routing. *Costo*: el Supervisor concentra complejidad (mitigado con
  validación semántica explícita).
- **D2 — Supervisor LLM + fallback determinista.** El LLM enruta, pero cada decisión se
  valida contra invariantes del estado; si falla, `_fallback_routing` decide por reglas.
  Combina flexibilidad y garantía de terminación (RF-03, RNF-01, RNF-03).
- **D3 — Anti-bucle en dos capas.** Semántica (`pasos >= max_pasos_red`) + sistémica
  (`recursion_limit=80`). Ningún input puede colgar el grafo.
- **D4 — Debate como nodo unificado.** En vez de N nodos, un panel con memoria compartida
  intra-nodo reduce el número de supersteps y concentra el intercambio entre pares.
- **D5 — Exportador determinista.** Separar la serialización del razonamiento permite
  alimentar al `evaluator/` de forma reproducible (P9, P10).
- **D6 — Cliente `httpx` único.** Evita el fallo de conexiones TCP nuevas por cada
  `ChatOpenAI` en entornos serverless (preludio del deploy en Cloud Run del estadio 04).
- **D7 — Reset de flags al ir a Redactor.** Al enrutar a `redactor` se resetean
  `debate/consenso/disenso/auditor/metodologo_ejecutado`, permitiendo una nueva ronda
  completa en la siguiente iteración.

## 6. Configuración (`config.py`)

| Variable | Default | Uso |
|---|---|---|
| `MAX_ITERATIONS` | 3 | Iteraciones de mejora |
| `MAX_DEBATE_ROUNDS` | 2 | Rondas del panel de debate |
| `RECURSION_LIMIT` | 80 | Capa sistémica anti-bucle |
| `get_max_pasos(max_iter)` | `max_iter*12+6` | Capa semántica anti-bucle |
| `GROQ_API_KEY_*` / `OPENAI_API_KEY` | — | Claves LLM (según nodo) |
| `CONTEXT_SOURCE`, `GCS_BUCKET_NAME`, `GDRIVE_RUBRIC_MAP` | local / — | Origen de contexto |

## 7. Riesgos

- Complejidad del Supervisor (muchas invariantes) → se documenta cada regla de validación.
- Crecimiento del `MentoriaState` (muchos campos) → se agrupa por dominio en la TypedDict.
- Coste de tokens del routing LLM por paso → terminación determinista temprana cuando es
  seguro (no llama al LLM si el ciclo ya está completo).
