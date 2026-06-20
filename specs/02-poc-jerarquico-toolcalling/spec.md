# Spec — POC #2: Jerarquía real con tool-calling + RAG

- **ID**: 02-poc-jerarquico-toolcalling
- **Estado**: Archivado (POC de referencia)
- **Origen**: `swarmsIA-jerarquica/mentoria_swarms`
- **Constitución aplicable**: P1, P2, P3, P4, P5, P6, P7, P9

## 1. Resumen

Segundo POC. La jerarquía deja de estar hardcodeada: el **Director es un LLM con
herramientas** y decide dinámicamente a quién convocar, en qué orden, cuántas veces
iterar y cuándo emitir veredicto. Añade **RAG dual** (biblioteca metodológica + tesis),
análisis de **dependencias cruzadas** entre secciones, **bucle de mejora** con
validación del texto propuesto y **Human-in-the-Loop** en Streamlit.

## 2. Objetivo y no-objetivos

**Objetivo**: que el sistema *razone* su propio flujo de mentoría (jerarquía emergente)
y fundamente cada observación con recuperación semántica, manteniendo control humano.

**No-objetivos**:
- Sin API HTTP ni frontend web (sigue siendo Streamlit local).
- Sin multi-tenant ni persistencia de sesiones entre usuarios.
- Sin streaming de progreso token a token (callbacks de fase, sí).

## 3. Usuarios y caso de uso

- **Mentor** que evalúa una sección a la vez, revisa el texto propuesto, lo edita y
  aprueba o re-analiza.

Flujo (4 pantallas):
1. **Biblioteca** — indexar (una vez) los libros de metodología de `/books`.
2. **Upload** — subir el PDF del proyecto; se segmenta en 7 secciones.
3. **Selección** — elegir la sección a evaluar (solo las detectadas).
4. **Revisión (HITL)** — el Director orquesta; el mentor edita el texto y aprueba o
   re-analiza (hasta `MAX_ITERACIONES`). **Resultado** — descarga `.txt`/`.json`.

## 4. Requisitos funcionales

- **RF-01 — Jerarquía por tool-calling.** El Director LLM dispone de herramientas
  atómicas (1 tool = 1 agente = 1 resultado) y decide el flujo. Python **no** hardcodea
  el orden. Herramientas: convocar Auditor, convocar Metodólogo, convocar Redactor
  (con instrucciones), revisar texto con el panel (Auditor/Metodólogo), convocar
  Consenso, convocar Disenso.
- **RF-02 — Auditor de rúbrica.** Evalúa los ítems de la sección (escala 0–3) con
  observación por ítem. Una sección está **aprobada** si todos sus ítems ≥ 2.
- **RF-03 — Metodólogo.** Analiza coherencia científica y **dependencias cruzadas**
  (p.ej. coherencia del Título con Planteamiento, Hipótesis y Metodología).
- **RF-04 — Redactor.** Produce texto mejorado siguiendo las instrucciones que el
  Director sintetiza a partir de los reportes.
- **RF-05 — Panel de revisión.** El texto propuesto puede re-validarse contra Auditor y
  Metodólogo para verificar que levantó las observaciones.
- **RF-06 — Consenso y Disenso.** Se consolida lo que los evaluadores acuerdan
  (Consenso) y lo que disputan (Disenso).
- **RF-07 — RAG dual.** Dos almacenes vectoriales independientes:
  - **Biblioteca** (persistente en disco): teoría de metodología, fundamenta observaciones.
  - **Tesis** (efímero en memoria): el proyecto del estudiante, recupera contexto exacto.
- **RF-08 — Dependencias cruzadas.** Al analizar una sección se recupera además contexto
  de las secciones relacionadas según un grafo de dependencias.
- **RF-09 — Veredicto final.** Nota vigesimal + estado (Aprobado/Observado) + fortalezas
  + observaciones + recomendación.
- **RF-10 — HITL.** El mentor edita el texto propuesto y decide aprobar o re-analizar.
- **RF-11 — Rúbrica UPAO.** Los 33 ítems, su mapeo a secciones y la tabla de notas son
  la fuente de verdad codificada en configuración.

## 5. Requisitos no funcionales

- **RNF-01 — Resiliencia a rate limits.** Pausa configurable entre agentes, soporte de
  claves por agente y backoff. Un análisis completo tarda ~3–6 min/sección.
- **RNF-02 — Garantías ante Director incompleto.** Si el Director agota loops/tokens y
  omite pasos, Python ejecuta **fallbacks garantizados**: si hay reporte de Auditor pero
  no texto → corre Redactor; si hay texto sin auditar → corre revisión; si faltan
  Consenso/Disenso y ambos evaluadores respondieron → los ejecuta; si no hay bloque
  "VEREDICTO DIRECTOR" → construye un veredicto de fallback con los datos disponibles.
- **RNF-03 — Aislamiento.** El workspace de agentes se limpia entre runs; embeddings
  locales en CPU (sin coste de API), normalización L2.
- **RNF-04 — Salidas tipadas.** El Auditor responde JSON validado; parseo tolerante.

## 6. Criterios de aceptación

- **CA-01**: El orden de convocatoria de agentes lo determina el Director LLM, no una
  secuencia fija en Python (verificable: cambia entre secciones/ejecuciones). *(RF-01)*
- **CA-02**: Toda observación del Auditor/Metodólogo puede rastrearse a contexto
  recuperado (sección + cruzado), no a conocimiento general del modelo. *(RF-07, RF-08, P3)*
- **CA-03**: Si el Director omite al Redactor por límite de loops, el sistema entrega
  texto mejorado igual (fallback). *(RNF-02)*
- **CA-04**: La biblioteca persiste entre reinicios; el índice de tesis se destruye al
  cerrar la sesión. *(RF-07)*
- **CA-05**: El mentor puede editar el texto propuesto y re-analizar hasta
  `MAX_ITERACIONES` veces. *(RF-10)*
- **CA-06**: Una sección con todos los ítems ≥ 2 se marca Aprobado; de lo contrario,
  Observado. *(RF-02, RF-09)*

## 7. Métrica de éxito del POC

Exitoso si (a) el flujo emergente del Director produce evaluaciones al menos tan
completas como el pipeline fijo del POC #1, y (b) las observaciones quedan **fundamentadas
en RAG**, reduciendo afirmaciones genéricas.

## 8. Limitaciones conocidas (motivan el POC #3)

- La jerarquía pura (todo pasa por el Director) crea un cuello de botella y dificulta el
  **debate entre pares** y la trazabilidad fina de cada paso.
- Swarms inyecta memoria/estado difícil de controlar; los fallbacks en Python crecen para
  compensar la imprevisibilidad del Director.
- La topología no es un grafo inspeccionable con checkpoints → se busca **LangGraph**.
