# Tasks — POC #1: Mentoría jerárquica orquestada en Python

> Descomposición ejecutable del [plan](./plan.md). Estado retrospectivo: todas
> completadas (POC archivado). Útil como checklist para reconstruir el estadio.

## Fase 0 — Andamiaje
- [x] T0.1 Estructura `backend/{core,agents,prompts}` + `frontend/`.
- [x] T0.2 `requirements.txt`: swarms, streamlit, pydantic, PyMuPDF, plotly, pandas, openai, tiktoken.
- [x] T0.3 Carga de `.env` y variables `WORKER_MODEL` / `DIRECTOR_MODEL` / `GROQ_API_KEY`.

## Fase 1 — Contratos de datos (bloquea a todo lo demás)
- [x] T1.1 `schemas.py`: `CriterioEvaluado` con validación de `puntaje ∈ {0,1,2,3}`.
- [x] T1.2 `ReporteAuditor`, `SugerenciaRedaccion`, `ReporteRedactor`.
- [x] T1.3 `SCORE_TABLE` + `calcular_nota_vigesimal` (normalización a 0–99) + `calcular_clasificacion`.
- [x] T1.4 `ReporteConsolidado` + `from_reportes(...)`.
- [x] T1.5 `extract_json_from_response` (3 estrategias de parseo).

## Fase 2 — Procesamiento de PDF
- [x] T2.1 `extract_text_from_pdf` (PyMuPDF).
- [x] T2.2 `split_into_sections` (segmentación por secciones del proyecto).
- [x] T2.3 `prepare_agent_contexts` (cada agente recibe solo su sección).
- [x] T2.4 `extract_titulo`.

## Fase 3 — Agentes
- [x] T3.1 `_create_swarms_agent` (`max_loops=1`, `autosave=False`, sin estado).
- [x] T3.2 `_run_with_retry` + `_run_silently` (reintento corto, truncado a 4 500 chars).
- [x] T3.3 Cinco auditores (`AuditorTitulo`…`AuditorAdministrativo`) con su mapa de ítems.
- [x] T3.4 `AgentRedactor.generar_sugerencias`.
- [x] T3.5 `DirectorAgent.sintetizar`.
- [x] T3.6 Prompts `.md` (uno por agente).

## Fase 4 — Orquestación
- [x] T4.1 `MentoriaOrchestrator.run` con `ThreadPoolExecutor` (5 auditores en paralelo).
- [x] T4.2 Manejo de fallo por futuro → `ReporteAuditor` de error, pipeline continúa.
- [x] T4.3 `_build_findings_summary` (criterios con puntaje ≤ 2).
- [x] T4.4 Cálculo de puntaje total + nota + síntesis del Director + `ReporteConsolidado`.
- [x] T4.5 Limpieza del `agent_workspace` al inicio/fin (aislamiento entre runs).
- [x] T4.6 Singleton `get_orchestrator` + `reset_orchestrator`.
- [x] T4.7 `progress_callback` para reflejar avance en la UI.

## Fase 5 — Frontend
- [x] T5.1 `frontend/app.py`: carga de PDF + barra de progreso + render del reporte.

## Verificación (mapeo a criterios de aceptación)
- [x] V1 PDF válido → reporte con nota /20 y 5 áreas. *(CA-01)*
- [x] V2 Fallo de un auditor → reporte parcial válido. *(CA-02)*
- [x] V3 Criterios ≤ 2 → sugerencias accionables. *(CA-03)*
- [x] V4 Misma entrada → misma nota. *(CA-04)*
- [x] V5 Dos runs seguidos sin fuga de estado. *(CA-05)*
