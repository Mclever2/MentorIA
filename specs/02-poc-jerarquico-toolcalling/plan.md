# Plan — POC #2: Jerarquía real con tool-calling + RAG

> Cómo se implementa la [spec](./spec.md).

## 1. Patrón arquitectónico

**Jerarquía multi-agente pura con tool-calling.** El Director es el nodo raíz; cada
herramienta involucra exactamente un sub-agente. El flujo **emerge del razonamiento del
LLM**, con una red de seguridad determinista en Python.

```
Director LLM (raíz, max_loops=20)
│  El contexto RAG viaja en closures de las herramientas (el Director no maneja chunks)
│
├─ tool: convocar_auditor()                → Auditor UPAO (ítems 0–3)
├─ tool: convocar_metodologico()           → Metodólogo (coherencia + dependencias)
│        [Director sintetiza ambos reportes → instrucciones]
├─ tool: convocar_redactor(instrucciones)  → Redactor (texto mejorado + argumento)
├─ tool: revisar_texto_auditor(texto)      → panel valida si levantó observaciones
├─ tool: convocar_consenso()               → acuerdos entre evaluadores
└─ tool: convocar_disenso()                → conflictos entre evaluadores
   →  VEREDICTO FINAL (nota vigesimal + estado + recomendaciones)

Red de seguridad (Python, post-run): si faltan Redactor / revisión / Consenso /
Disenso / veredicto, se ejecutan/construyen automáticamente con los datos disponibles.
```

## 2. Stack tecnológico

| Componente | Tecnología |
|---|---|
| Orquestación | Swarms ≥ 7.0 con `tools=[...]` y `max_loops=20` |
| LLM (Director + Workers) | `llama-3.3-70b-versatile` vía Groq (proveedor configurable) |
| Embeddings | HuggingFace `sentence-transformers/all-MiniLM-L6-v2` (CPU, L2) |
| Vector store biblioteca | ChromaDB **persistente** en `chroma_db/` |
| Vector store tesis | ChromaDB **efímero** (EphemeralClient, en RAM) |
| Chunking / RAG | LangChain text-splitters + langchain-chroma |
| Extracción PDF | pdfplumber |
| Frontend | Streamlit ≥ 1.35 (4 pantallas + sidebar) |
| Validación | Pydantic v2 |

## 3. Componentes

| Módulo | Responsabilidad |
|---|---|
| `backend/agents/director.py` | `DirectorOrchestrator`: construye sub-agentes una vez; por run crea herramientas (closures) y un Director; ejecuta y aplica fallbacks garantizados |
| `backend/agents/herramientas.py` | Fábrica de las herramientas atómicas; inyecta contexto RAG por closure |
| `backend/agents/auditor.py` | Evaluación de ítems 0–3 + `ReporteAuditor` (`aprobado`, `items_evaluados`) |
| `backend/agents/metodologico.py` | Coherencia científica + dependencias cruzadas |
| `backend/agents/redactor.py` | Texto mejorado según instrucciones |
| `backend/rag/embeddings.py` | Carga del modelo MiniLM-L6-v2 |
| `backend/rag/extractor.py` | Extracción PDF + segmentación en secciones |
| `backend/rag/library_store.py` | Biblioteca persistente (precarga desde `/books`, 800/100) |
| `backend/rag/tesis_store.py` | Índice efímero (`build_tesis_store`, `query_context`, `query_cross_context`, 600/80) |
| `backend/rag/rubric_parser.py` | Parseo de rúbrica |
| `backend/config.py` | `RUBRICA_ITEMS_UPAO` (33), `SECCIONES`, `CROSS_DEPS`, `CROSS_QUERIES`, `SECTION_QUERIES`, `SCORE_TABLE`, `puntaje_a_nota` |
| `backend/utils.py` | `run_agent_silently`, `extract_json`, `call_with_backoff`, `use_*_key` |
| `frontend/` | `app.py` (router 4 pantallas) + `components/` + `resources.py` (singletons cacheados) + `session_manager.py` |

## 4. Modelo de datos / configuración (`backend/config.py`)

- **`RUBRICA_ITEMS_UPAO`** — 33 ítems con descripción.
- **`SECCIONES`** — mapeo sección → ítems asignados (7 secciones).
- **`CROSS_DEPS`** — grafo de dependencias cruzadas entre secciones.
- **`CROSS_QUERIES` / `SECTION_QUERIES`** — queries semánticas por sección y por par.
- **`SCORE_TABLE`** + `puntaje_a_nota(pct)` — puntaje → nota vigesimal (máx 99).

## 5. Decisiones de diseño y trade-offs

- **D1 — Tool-calling en vez de pipeline.** *Ventaja*: jerarquía emergente, el sistema
  decide profundizar. *Costo*: imprevisibilidad → necesidad de fallbacks (D4).
- **D2 — RAG dual (persistente vs efímero).** Separar teoría (reutilizable, en disco)
  de proyecto del estudiante (privado, en RAM) cumple P3 y P7.
- **D3 — Contexto por closures.** Las herramientas capturan el contexto RAG; el Director
  recibe **resúmenes estructurados**, no fragmentos de PDF → menos tokens, menos ruido.
- **D4 — Fallbacks garantizados.** El Director LLM puede agotar `max_loops`/tokens; tras
  el run, Python verifica el `state` compartido y completa Redactor / revisión /
  Consenso / Disenso / veredicto. Garantiza salida útil al frontend (RNF-02).
- **D5 — Embeddings locales.** MiniLM-L6-v2 en CPU evita coste y dependencia de API de
  embeddings; normalización L2 para similitud coseno.
- **D6 — Resiliencia a rate limits.** `SLEEP_BETWEEN_AGENTS=20`, claves por agente,
  `call_with_backoff`.

## 6. Configuración (variables de entorno)

| Variable | Default | Uso |
|---|---|---|
| `GROQ_API_KEY` | — | Fallback global |
| `GROQ_KEY_{DIRECTOR,AUDITOR,METODOLOGICO,REDACTOR}` | — | Clave por agente (evita 429) |
| `MAX_ITERACIONES` | 3 | Ciclos de mejora por sección |
| `SLEEP_BETWEEN_AGENTS` | 20 | Pausa entre llamadas (s) |
| `LITELLM_LOG` / `SWARMS_VERBOSE` | ERROR / false | Silenciado de logs de terceros |

## 7. Riesgos

- Imprevisibilidad del Director (mitigado por D4, pero los fallbacks crecen).
- Memoria persistente de Swarms entre runs (mitigado limpiando `agent_workspace`).
- Rate limits del tier gratuito (mitigado por claves múltiples + sleep + backoff).
