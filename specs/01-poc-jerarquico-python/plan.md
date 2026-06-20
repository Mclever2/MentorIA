# Plan — POC #1: Mentoría jerárquica orquestada en Python

> Cómo se implementa la [spec](./spec.md). Arquitectura, stack y decisiones.

## 1. Patrón arquitectónico

**Jerarquía con orquestación explícita en Python.** El `MentoriaOrchestrator` es el
punto de entrada único e implementa el flujo a mano (no hay tool-calling): el LLM
genera texto, Python decide el orden.

```
MentoriaOrchestrator.run(pdf_bytes)
  │
  1. pdf_processor: extract_text → split_into_sections → prepare_agent_contexts → extract_titulo
  │
  2. ThreadPoolExecutor (5 workers en paralelo)
  │     ├─ AuditorTitulo            (ítems 01–03)
  │     ├─ AuditorProblema          (ítems 04–10)
  │     ├─ AuditorTeoricoVariables  (ítems 11–21)
  │     ├─ AuditorMetodologico      (ítems 22–27)
  │     └─ AuditorAdministrativo    (ítems 28–33)
  │
  3. _build_findings_summary  (criterios con puntaje ≤ 2)
  │
  4. AgentRedactor.generar_sugerencias(findings)
  │
  5. DirectorAgent.sintetizar(reportes, redactor, nota...)  → feedback empático
  │
  6. ReporteConsolidado.from_reportes(...)   → nota vigesimal + clasificación
```

## 2. Stack tecnológico

| Componente | Tecnología |
|---|---|
| Orquestación de agentes | [Swarms](https://github.com/kyegomez/swarms) ≥ 7.0 (`Agent`, `max_loops=1`) |
| LLM workers | `groq/llama-3.1-8b-instant` (configurable vía `WORKER_MODEL`) |
| LLM director | `groq/llama-3.3-70b-versatile` (configurable vía `DIRECTOR_MODEL`) |
| Extracción PDF | PyMuPDF |
| Validación | Pydantic v2 |
| Frontend | Streamlit ≥ 1.35 |
| Gráficos / datos | plotly, pandas |
| Conteo de tokens | tiktoken |
| Paralelismo | `concurrent.futures.ThreadPoolExecutor` |

## 3. Modelo de datos (Pydantic — `backend/core/schemas.py`)

- **`CriterioEvaluado`**: `numero`, `descripcion`, `puntaje` (0–3, validado),
  `observacion`, `evidencia?`.
- **`ReporteAuditor`**: `agente`, `seccion`, `criterios[]`, `puntaje_obtenido`,
  `puntaje_maximo`, `fortalezas[]`, `debilidades[]`.
- **`SugerenciaRedaccion`**: `criterio_relacionado`, `fragmento_detectado`,
  `propuesta_mejora`, `justificacion`.
- **`ReporteRedactor`**: `sugerencias[]`, `comentario_estilo_general`,
  `nivel_rigor_academico`.
- **`ReporteConsolidado`**: agregado final (`titulo_proyecto`, reportes, puntajes,
  `porcentaje_logro`, `nota_vigesimal`, `clasificacion`, `feedback_mentor`,
  `errores_procesamiento`).

**Conversión de nota**: `SCORE_TABLE` (tramos puntaje→nota) + `calcular_nota_vigesimal`
(normaliza el puntaje obtenido a escala 0–99 antes de mapear) + `calcular_clasificacion`.

## 4. Componentes

| Módulo | Responsabilidad |
|---|---|
| `backend/core/orchestrator.py` | Pipeline completo + singleton reutilizable + reporte de error |
| `backend/core/pdf_processor.py` | Extracción y segmentación del PDF en secciones |
| `backend/core/schemas.py` | Esquemas tipados + tabla de notas + `extract_json_from_response` |
| `backend/agents/workers.py` | Fábrica de los 5 auditores + redactor; `_run_with_retry` |
| `backend/agents/director.py` | Síntesis del feedback final |
| `backend/prompts/*.md` | System prompts (uno por auditor + redactor + director) |
| `frontend/app.py` | UI Streamlit de carga + visualización del reporte |

## 5. Decisiones de diseño y trade-offs

- **D1 — Orquestación en Python (no tool-calling).** *Ventaja*: predecible, fácil de
  depurar, barato en tokens. *Costo*: el sistema no puede decidir iterar ni profundizar.
  → Este límite motiva el POC #2.
- **D2 — Auditores en paralelo.** Cada agente recibe **solo su sección** (`prepare_agent_contexts`),
  reduciendo contexto y coste, y permitiendo concurrencia con `ThreadPoolExecutor`.
- **D3 — `max_loops=1` + `autosave=False`.** Workers de una sola pasada y sin estado
  persistente, para garantizar aislamiento entre análisis (RNF-02).
- **D4 — Parseo defensivo.** `extract_json_from_response` intenta parseo directo →
  bloque ```json``` → primer `{` … último `}`. `_run_with_retry` reintenta con una
  corrección corta (no reenvía el task completo, para no inflar el contexto) y trunca el
  task a 4 500 chars por si el framework inyecta memoria.
- **D5 — Tolerancia a fallo de auditor.** Si un futuro lanza excepción, se sustituye por
  un `ReporteAuditor` de error con puntaje 0 y el pipeline continúa (CA-02).

## 6. Configuración

| Variable | Default | Uso |
|---|---|---|
| `WORKER_MODEL` | `groq/llama-3.1-8b-instant` | Modelo de los auditores y redactor |
| `DIRECTOR_MODEL` | `groq/llama-3.3-70b-versatile` | Modelo del director sintetizador |
| `GROQ_API_KEY` | — | Clave del proveedor LLM |

## 7. Riesgos

- Rate limits de Groq en tier gratuito (mitigado parcialmente por modelos pequeños en
  workers).
- Segmentación de secciones por heurística de texto: PDFs mal estructurados degradan la
  precisión del *chunking*.
