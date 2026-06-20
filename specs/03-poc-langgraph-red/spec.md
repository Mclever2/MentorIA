# Spec — POC #3: Red multiagente pura en LangGraph

- **ID**: 03-poc-langgraph-red
- **Estado**: Archivado (base directa del estadio 04)
- **Origen**: `langgraph-red/poc_langgraph_mentoria`
- **Constitución aplicable**: P1–P5, P8, P9, P10

## 1. Resumen

Tercer POC. Reescribe la orquestación como un **grafo de estados (LangGraph)** con
topología de **red pura**: un único **Supervisor** decide en cada paso qué nodo ejecutar;
todos los nodos vuelven al Supervisor. Reemplaza la jerarquía por tool-calling de Swarms
por un grafo **inspeccionable, con checkpoints y protección anti-bucle en dos capas**.
Incorpora un **nodo de debate** (panel de subagentes con memoria compartida), un
**exportador** de artefactos y un **evaluador** con métricas cuantitativas.

## 2. Objetivo y no-objetivos

**Objetivo**: una orquestación determinista-pero-dinámica, trazable y medible, que
elimine la imprevisibilidad de la jerarquía Swarms y sirva de base para el producto.

**No-objetivos**:
- No es aún un producto desplegado (sin chat conversacional, multi-tenant ni React; la
  UI sigue siendo Streamlit y hay una API mínima legacy).

## 3. Usuarios y caso de uso

- **Mentor** que evalúa una sección y obtiene texto mejorado + métricas, con trazas
  exportadas a disco.

## 4. Requisitos funcionales

- **RF-01 — Topología de red pura.** `StateGraph` con punto de entrada en el Supervisor;
  arista condicional Supervisor→nodo; todos los nodos regresan al Supervisor; `fin`
  enruta al Exportador y de ahí a `END`.
- **RF-02 — Supervisor como router LLM.** El Supervisor lee el estado completo y un LLM
  decide el siguiente nodo entre: `redactor`, `auditor`, `metodologico`, `debate`,
  `consenso`, `disenso`, `fin`. Escribe `siguiente_nodo` en el estado; el router solo lo lee.
- **RF-03 — Validación semántica de la decisión.** La decisión del LLM se valida contra
  el estado (p.ej. no ir a `consenso` sin Auditor y Metodólogo completos; no `fin` sin
  Auditor ejecutado ni texto generado). Si es inválida, se aplica **fallback determinista**.
- **RF-04 — Nodos especializados.** Auditor (rúbrica), Metodólogo (rigor + coherencia
  cruzada), Redactor (reescritura iterada), Consenso, Disenso.
- **RF-05 — Nodo de debate.** Panel de subagentes con **memoria compartida intra-nodo**
  que produce un veredicto estructurado del sintetizador; el debate solo corre si hay
  errores activos y quedan iteraciones.
- **RF-06 — Iteración controlada.** El Redactor incrementa `numero_iteracion`; el ciclo
  termina al alcanzar `max_iteraciones` **con texto generado y auditado**.
- **RF-07 — Exportador.** Nodo sin LLM que serializa el estado final a artefactos en
  disco (`run_*.json`, `debate_*.md`, `eval_*.json`).
- **RF-08 — Evaluador de métricas.** A partir de los artefactos: *gain score*
  (inicial→final vía juez LLM), *cosine similarity*, *context precision*, *kappa* de
  acuerdo entre evaluadores, *ROUGE/BLEU*.
- **RF-09 — RAG.** Recuperación de contexto de la sección, dependencias y biblioteca
  teórica (reutiliza el patrón dual del POC #2).
- **RF-10 — Rúbrica dinámica (opcional).** Soporta una rúbrica parseada subida por el
  estudiante además de la rúbrica base.

## 5. Requisitos no funcionales

- **RNF-01 — Anti-bucle en dos capas.**
  1. *Semántica*: si `pasos_ejecutados >= max_pasos_red` el Supervisor fuerza `fin` sin
     llamar al LLM (`max_pasos = max_iter*12 + 6`).
  2. *Sistémica*: `recursion_limit = 80` supersteps como red de seguridad de LangGraph.
- **RNF-02 — Checkpointing.** `MemorySaver` con `thread_id` por run para estado
  recuperable e inspección.
- **RNF-03 — Tolerancia a fallos del LLM.** Backoff en las invocaciones; si el LLM del
  Supervisor falla o devuelve un valor fuera de `NODOS_VALIDOS`, cae al fallback
  determinista (nunca queda en bucle).
- **RNF-04 — Cliente HTTP compartido.** Un único cliente `httpx` para todos los LLMs
  (evita fallos intermitentes de conexiones nuevas en entornos serverless).
- **RNF-05 — Trazabilidad.** `run_id` (UUID) por flujo; logs por paso del Supervisor.

## 6. Criterios de aceptación

- **CA-01**: El flujo nunca excede `max_pasos_red` ni el `recursion_limit`; ante decisión
  inválida del LLM, continúa por fallback determinista. *(RF-03, RNF-01, RNF-03)*
- **CA-02**: `consenso`/`disenso` solo se ejecutan si Auditor y Metodólogo ya corrieron;
  `fin` solo si hay Auditor ejecutado y texto generado (salvo límite de pasos). *(RF-03)*
- **CA-03**: El ciclo termina exactamente cuando `numero_iteracion >= max_iteraciones`,
  hay `texto_iterado` y el Auditor evaluó esa última versión. *(RF-06)*
- **CA-04**: Cada run deja en disco `run_*.json` (+ `debate_*.md` si hubo debate) y un
  `eval_*.json` con las métricas. *(RF-07, RF-08, RNF-05)*
- **CA-05**: El *gain score* compara la evaluación del texto inicial contra la del final.
  *(RF-08, P9)*

## 7. Métrica de éxito del POC

Exitoso si reproduce la calidad de mentoría del POC #2 con (a) **cero bucles infinitos**,
(b) **trazas inspeccionables** y (c) **métricas cuantitativas** que evidencien mejora
inicial→final.

## 8. Limitaciones conocidas (motivan el estadio 04)

- Sigue siendo un POC: interacción por Streamlit, sin chat conversacional, sin gestión de
  documentos/rúbricas/universidad por usuario, sin streaming HTTP ni cancelación, sin
  despliegue gestionado. Esos huecos son exactamente el alcance del estadio 04.
