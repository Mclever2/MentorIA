# Especificaciones — MentorIA (Spec-Driven Development)

Este directorio documenta el sistema de **mentoría académica multiagente** siguiendo
la metodología **Spec-Driven Development (SDD)** al estilo *GitHub Spec Kit*: la
especificación es la fuente de verdad y el código es una implementación de la spec,
no al revés.

El producto nació como una serie de **pruebas de concepto** que fueron evolucionando
en arquitectura. Cada estadio está documentado como una *feature spec* independiente
para dejar trazable **qué se construyó, por qué, y cómo se llegó a la versión actual**.

## Estructura

```
specs/
├─ constitution.md                  # Principios transversales (gobiernan TODAS las specs)
├─ README.md                        # Este índice
│
├─ 01-poc-jerarquico-python/        # POC #1 — jerarquía orquestada en Python (Swarms)
│  ├─ spec.md                       #   QUÉ y POR QUÉ (requisitos + criterios de aceptación)
│  ├─ plan.md                       #   CÓMO (arquitectura, stack, decisiones)
│  └─ tasks.md                      #   PASOS (tareas ejecutables)
│
├─ 02-poc-jerarquico-toolcalling/   # POC #2 — jerarquía real con tool-calling + RAG
│  ├─ spec.md  plan.md  tasks.md
│
├─ 03-poc-langgraph-red/            # POC #3 — migración a red pura LangGraph
│  ├─ spec.md  plan.md  tasks.md
│
└─ 04-langgraph-mentoria-prod/      # ACTUAL — productización (FastAPI + React + Cloud Run)
   ├─ spec.md  plan.md  tasks.md
```

## Línea evolutiva

| # | Estadio | Patrón de orquestación | Decisión que abre el siguiente | Repo de origen |
|---|---------|------------------------|-------------------------------|----------------|
| 01 | POC jerárquico (Python) | Director→Workers **hardcodeado en Python**; 5 auditores en paralelo | El flujo rígido no escala a iteración ni decisiones dinámicas | `swarmsIA-jerarquica/poc_sistema_mentoria` |
| 02 | POC jerárquico (tool-calling) | Director **LLM decide** vía herramientas atómicas; + RAG dual | La jerarquía pura limita el debate entre pares y la trazabilidad | `swarmsIA-jerarquica/mentoria_swarms` |
| 03 | POC red pura (LangGraph) | **Supervisor-router** sobre `StateGraph`; nodos que vuelven al supervisor | El POC funciona pero no es un producto (sin API, chat, multi-tenant) | `langgraph-red/poc_langgraph_mentoria` |
| 04 | Productización | Misma red + **FastAPI + React + Cloud Run**, chat con intención, rúbrica/universidad dinámicas | *(versión actual en desarrollo)* | `poc_langgraph_mentoria` (este repo) |

## Cómo usar estas specs (flujo SDD)

1. **`constitution.md`** fija los principios no negociables. Toda spec debe cumplirlos.
2. **`spec.md`** (por feature) define el comportamiento esperado — sin atarse a tecnología.
   Cada requisito tiene **criterios de aceptación verificables**.
3. **`plan.md`** traduce la spec a arquitectura concreta y registra las decisiones/trade-offs.
4. **`tasks.md`** descompone el plan en tareas ordenadas y marcables.
5. Al implementar o cambiar algo: **primero se actualiza la spec**, luego el código.

> Convención de estado: cada `spec.md` declara su `Estado` (`Implementado`, `Parcial`,
> `Planeado`, `Archivado`). Los estadios 01–03 son POCs **archivados** que sirven de
> referencia histórica; el estadio 04 es el que está **vivo**.
