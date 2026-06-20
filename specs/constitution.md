# Constitución del producto — MentorIA

> Principios transversales que gobiernan **todas** las specs de este repositorio.
> Una feature spec puede añadir restricciones, pero **no puede violar** estos principios.
> Si una decisión de diseño contradice la constitución, se cambia la decisión o se
> enmienda la constitución de forma explícita (con fecha y motivo).

## 1. Misión

Asistir a estudiantes y mentores en la mejora de **proyectos de tesis** evaluándolos
contra una **rúbrica oficial**, explicando las observaciones y proponiendo texto
mejorado. El sistema es un **mentor**, no un autocompletado: enseña el criterio, no
solo entrega una nota.

## 2. Principios de arquitectura

- **P1 — Roles separados y auditables.** Cada responsabilidad vive en un agente
  distinto: *evaluar* (Auditor), *coherencia científica* (Metodólogo), *reescribir*
  (Redactor), *orquestar* (Director/Supervisor), *consolidar acuerdos/conflictos*
  (Consenso/Disenso). Ningún agente acumula dos roles.
- **P2 — La rúbrica es la fuente de verdad.** Toda evaluación se ancla a ítems de
  rúbrica con escala explícita (0–3) y conversión determinista a nota vigesimal.
  El juicio del LLM nunca reemplaza a la rúbrica como nota oficial.
- **P3 — Fundamentar, no alucinar (RAG).** Las observaciones deben apoyarse en el
  texto real del estudiante y en bibliografía metodológica recuperada. Se separan
  dos almacenes: **biblioteca** (persistente, teoría) y **tesis** (efímero, por sesión).
- **P4 — Salidas tipadas y validadas.** Toda salida estructurada de un agente se
  valida contra un esquema (Pydantic / parseo JSON robusto con reintento). Una
  respuesta no parseable no rompe el flujo: degrada a un fallback con datos parciales.
- **P5 — Orquestación tolerante a fallos.** Rate limits y respuestas inválidas son
  el caso normal, no la excepción: backoff exponencial, rotación de claves, fallback
  determinista y protección anti-bucle son obligatorios en cualquier orquestador.

## 3. Principios de producto

- **P6 — Human-in-the-Loop.** El mentor decide. El sistema propone; el humano aprueba,
  edita o re-ejecuta.
- **P7 — El PDF del estudiante es inmutable.** El sistema nunca modifica el documento
  original. El texto corregido vive solo en la **memoria del sistema** (RAG), y su
  incorporación es una decisión explícita del usuario.
- **P8 — Transparencia del proceso.** El usuario ve qué agente está actuando y por qué.
  Cada ejecución es trazable (identificador de run, logs, artefactos exportados).

## 4. Principios de calidad

- **P9 — Mejora medible.** El efecto de una iteración se mide (p.ej. *gain score*
  inicial→final, acuerdo entre evaluadores, similitud, precisión de contexto). "Mejoró"
  es una afirmación con número detrás.
- **P10 — Reproducibilidad.** Mismo input + misma config ⇒ mismo flujo lógico. Los
  parámetros (modelo, temperatura, nº de iteraciones, límites) son configurables por
  entorno, no hardcodeados.

## 5. Restricciones técnicas vigentes (estadio 04)

- **Idioma**: español (dominio académico peruano; rúbrica base UPAO de referencia).
- **Despliegue**: Google Cloud Run con `min-instances=1`.
- **Estado**: vector store **en memoria** del proceso; **1 run por instancia**
  (lock exclusivo). El registro de documentos/runs no es persistente entre reinicios.
- **Entorno local**: usar el intérprete del venv (`venv\Scripts\python.exe`).
- **Proveedor LLM**: configurable por entorno (rotación de claves Groq por defecto en
  el backend de producción; los POCs usaron Groq y/o OpenAI según el estadio).

## 6. Glosario

| Término | Significado |
|---|---|
| **Sección** | Parte del proyecto de tesis (Título, Planteamiento, Marco Teórico, Hipótesis/Variables, Metodología, Aspectos Administrativos, Referencias). |
| **Ítem de rúbrica** | Criterio evaluable individual con escala 0–3. |
| **Run** | Una ejecución del flujo de evaluación sobre una o más secciones. |
| **Memoria RAG** | Representación vectorial del proyecto que el sistema "recuerda"; distinta del PDF. |
| **Mejora pendiente** | Texto corregido por el Redactor aún no incorporado a la memoria RAG. |
| **Gain score** | Diferencia de calidad entre el texto inicial y el final, según juez LLM. |

---

### Enmiendas

| Fecha | Cambio | Motivo |
|---|---|---|
| 2026-06-19 | Versión inicial de la constitución, destilada de los 4 estadios del producto. | Adoptar Spec-Driven Development. |
