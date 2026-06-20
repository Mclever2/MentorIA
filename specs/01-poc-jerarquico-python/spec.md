# Spec — POC #1: Mentoría jerárquica orquestada en Python

- **ID**: 01-poc-jerarquico-python
- **Estado**: Archivado (POC de referencia)
- **Origen**: `swarmsIA-jerarquica/poc_sistema_mentoria`
- **Constitución aplicable**: P1, P2, P4, P9 (P3 RAG y P6 HITL aún no presentes)

## 1. Resumen

Primera prueba de concepto. Demuestra que un **enjambre de agentes especializados**
puede evaluar un proyecto de tesis contra una rúbrica y producir un **reporte
consolidado** con nota vigesimal y feedback. La orquestación es **explícita en Python**:
el LLM solo genera contenido, el flujo lo controla el código.

## 2. Objetivo y no-objetivos

**Objetivo**: validar la viabilidad de descomponer la evaluación de una tesis en
agentes por área de la rúbrica, ejecutarlos en paralelo y consolidar un veredicto único.

**No-objetivos** (explícitamente fuera de este estadio):
- Sin RAG / sin recuperación semántica (cada agente recibe su sección como texto plano).
- Sin bucle de iteración ni reescritura aplicada (el Redactor solo *sugiere*).
- Sin Human-in-the-Loop (es un reporte de una sola pasada).
- Sin API ni multi-usuario (app Streamlit local de un solo uso).

## 3. Usuarios y caso de uso

- **Mentor / estudiante** sube el PDF del proyecto y obtiene un informe de evaluación.

Flujo de usuario:
1. Sube el PDF del proyecto de tesis.
2. El sistema procesa y evalúa automáticamente (sin más interacción).
3. Recibe un reporte: nota /20, puntaje por sección, fortalezas/debilidades y sugerencias.

## 4. Requisitos funcionales

- **RF-01 — Ingesta de PDF.** El sistema extrae el texto del PDF y lo segmenta en las
  secciones del proyecto.
- **RF-02 — Evaluación por área.** Cinco auditores evalúan grupos de ítems de la rúbrica:
  - Título (ítems 01–03)
  - Planteamiento del Problema (04–10)
  - Marco Teórico + Hipótesis y Variables (11–21)
  - Marco Metodológico (22–27)
  - Aspectos Administrativos + Referencias (28–33)
- **RF-03 — Ejecución en paralelo.** Los cinco auditores corren concurrentemente; un
  fallo en uno no aborta a los demás.
- **RF-04 — Puntaje por ítem.** Cada ítem recibe puntaje 0–3 con observación
  argumentada y, cuando sea posible, evidencia textual.
- **RF-05 — Sugerencias de redacción.** Un Redactor genera propuestas de mejora para
  los criterios con puntaje ≤ 2 (texto detectado → propuesta → justificación).
- **RF-06 — Síntesis del Director.** Un Director produce el feedback final empático a
  partir de los reportes de auditores y del redactor.
- **RF-07 — Nota vigesimal.** El puntaje bruto se normaliza a escala 0–99 y se convierte
  a nota 0–20 mediante tabla determinista; se deriva una clasificación
  (Insuficiente/Regular/Bueno/Excelente).
- **RF-08 — Reporte consolidado.** Salida única con título detectado, reportes por
  sección, sugerencias, puntaje total, porcentaje de logro, nota y feedback.

## 5. Requisitos no funcionales

- **RNF-01 — Robustez de parseo.** Toda salida de agente se valida contra esquema; si
  el JSON es inválido se reintenta y, si persiste, se degrada a un reporte vacío sin
  romper el pipeline.
- **RNF-02 — Aislamiento entre ejecuciones.** No debe filtrarse memoria/estado de un
  análisis al siguiente (el workspace del framework de agentes se limpia).
- **RNF-03 — Configurable por entorno.** Modelos de worker y director ajustables por
  variables de entorno.

## 6. Criterios de aceptación

- **CA-01**: Dado un PDF de tesis válido, el sistema devuelve un reporte con nota /20 y
  desglose por las 5 áreas. *(RF-01, RF-02, RF-07, RF-08)*
- **CA-02**: Si un auditor falla, el reporte se entrega igual, marcando esa sección con
  error y puntaje 0 — los demás puntajes son válidos. *(RF-03, RNF-01)*
- **CA-03**: Cada criterio con puntaje ≤ 2 genera al menos una sugerencia de mejora
  accionable. *(RF-05)*
- **CA-04**: La nota vigesimal es función determinista del puntaje bruto (misma entrada ⇒
  misma nota). *(RF-07, P10)*
- **CA-05**: Dos análisis consecutivos en la misma sesión no comparten estado. *(RNF-02)*

## 7. Métrica de éxito del POC

Se considera exitoso si produce reportes coherentes con el criterio de un mentor humano
en proyectos de muestra, demostrando que la **descomposición por agentes** es viable —
independientemente de la calidad fina del texto.

## 8. Limitaciones conocidas (motivan el POC #2)

- El flujo rígido en Python no permite que el sistema **decida** iterar o profundizar.
- Sin RAG, las observaciones no se anclan en bibliografía ni recuperan contexto cruzado.
- El Redactor sugiere pero no hay ciclo de mejora ni validación del texto propuesto.
