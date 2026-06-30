"""
Mini-grafo de DEBATE RÁPIDO — mejora de texto sin lanzar la red de evaluación.

Arquitectura (macro = red / micro = secuencial), respaldada por los antecedentes
del proyecto:
  - Red macro: un `StateGraph` de LangGraph coordina agentes especializados
    (como GraphMASAL, Zeng et al. 2025).
  - Lógica secuencial interna: cada nodo procesa en pasos (como EduPlanner,
    Zhang et al. 2025: Evaluator → Optimizer → Analyst).
  - Debate por roles diferenciados activados en secuencia (como Du et al. 2025:
    afirmativo / negativo / moderador).

Flujo:
  recuperacion → metodologo_rigor → metodologo_coherencia → sintetizador → estructurador

  - metodologo_rigor + metodologo_coherencia = la RED DE DEBATE (memoria compartida,
    roles distintos, el 2º responde al 1º).
  - sintetizador (redactor-árbitro) resuelve el debate y produce el texto mejorado.
  - estructurador (conversador) entrega la respuesta de chat, simple y sin panel.

Todo corre con gpt-4o-mini (llm_rapido): rápido y fuera del presupuesto del grafo
grande. Se usa SOLO para mejorar/corregir/redactar; si el estudiante pide EVALUAR,
el grafo grande es el que actúa.
"""

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from .llm import llm_rapido

logger = logging.getLogger(__name__)

_FALLBACK = (
    "Disculpa, tuve un problema preparando la mejora de tu texto. "
    "Intenta de nuevo en unos segundos."
)


# ── Estado compartido (blackboard del debate) ───────────────────────────────

class EstadoDebate(TypedDict, total=False):
    # entrada
    consulta: str
    historial: list
    doc: Any
    biblioteca: Any
    # recursos (los puebla el nodo recuperacion)
    contexto_libros: str
    contexto_tesis: str
    criterios_rubrica: str
    seccion: str
    enfoque: str
    estado_proyecto: str
    # debate (memoria compartida)
    debate_memory: list
    # salida
    texto_sintetizado: str
    recomendaciones: str
    respuesta_final: str


class SintesisDebate(BaseModel):
    """Entregable del redactor-árbitro: texto mejorado + observaciones aparte."""
    texto_mejorado: str = Field(
        description=(
            "Versión mejorada de SOLO el fragmento/sección que pidió el estudiante, "
            "lista para entregar. Sin notas ni avisos dentro: solo el texto de la tesis. "
            "Respeta el enfoque; no fuerces lo que el tipo de investigación no requiere. "
            "Las tablas, en markdown simple. Cadena vacía si la consulta no pedía reescribir texto."
        )
    )
    recomendaciones: str = Field(
        default="",
        description=(
            "Observaciones que NO van dentro del texto: incongruencias con el enfoque/diseño, "
            "problemas de coherencia con otras secciones, redactadas como sugerencias accionables. "
            "Cadena vacía si no hay nada que observar."
        ),
    )


def _formatear_memoria(debate_memory: list) -> str:
    if not debate_memory:
        return "(aún no hay intervenciones del panel)"
    partes = []
    for e in debate_memory:
        partes.append(f"[{e.get('agente', '?')}]\n{e.get('contenido', '')}")
    return "\n\n".join(partes)


# ── Prompts de los agentes ──────────────────────────────────────────────────

_PROMPT_RIGOR = """\
Eres el METODÓLOGO DE RIGOR en un panel que ayuda a un estudiante a MEJORAR un fragmento de su \
tesis (NO a calificarlo). {especialista}

{enfoque}

Fundamenta SIEMPRE tu análisis en los FRAGMENTOS DE LIBROS (tu memoria metodológica). No inventes \
autores, teorías ni citas que no estén ahí.

CONSULTA DEL ESTUDIANTE:
{consulta}

TEXTO ACTUAL DEL ESTUDIANTE (puede venir partido en fragmentos: reensámblalo, no asumas que algo \
falta solo porque no aparece en el primer fragmento):
{contexto_tesis}

CRITERIOS DE LA RÚBRICA A SATISFACER:
{criterios_rubrica}

FRAGMENTOS DE LIBROS:
{contexto_libros}

Da tu postura de forma BREVE y concreta: qué está bien, qué falla metodológicamente y CÓMO debería \
mejorarse para cumplir los criterios y alcanzar el máximo puntaje. Todavía NO reescribas el texto."""

_PROMPT_COHERENCIA = """\
Eres el METODÓLOGO DE COHERENCIA Y CONTEXTO en el mismo panel. Tu foco: la coherencia con el resto \
del proyecto, la viabilidad y el ajuste al tipo/diseño de investigación.

{enfoque}

El METODÓLOGO DE RIGOR ya dio su postura. DEBES responder directamente a su argumento (coincidir o \
discrepar en al menos un punto) antes de añadir el tuyo. Fundamenta en los libros; no inventes citas.

CONSULTA DEL ESTUDIANTE:
{consulta}

TEXTO ACTUAL DEL ESTUDIANTE:
{contexto_tesis}

CRITERIOS DE LA RÚBRICA A SATISFACER:
{criterios_rubrica}

FRAGMENTOS DE LIBROS:
{contexto_libros}

POSTURA DEL METODÓLOGO DE RIGOR (responde a esto):
{historial_panel}

Estructura tu respuesta así:
REACCIÓN AL RIGOR: [¿coincides o discrepas? ¿por qué?]
MI APORTE DE COHERENCIA: [lo que él no consideró: consistencia con otras secciones, viabilidad, ajuste al tipo]
CAMINO AL MÁXIMO PUNTAJE: [qué debe cumplir el estudiante]. Sé breve y concreto."""

_PROMPT_SINTETIZADOR = """\
Eres el REDACTOR-ÁRBITRO del panel. No debates: RESUELVES el debate de los dos metodólogos y produces \
el entregable. Toma lo más sólido de cada postura y descarta lo que fue refutado.

{enfoque}

CONSULTA DEL ESTUDIANTE:
{consulta}

TEXTO ORIGINAL DEL ESTUDIANTE:
{contexto_tesis}

CRITERIOS DE LA RÚBRICA:
{criterios_rubrica}

DEBATE COMPLETO DE LOS METODÓLOGOS:
{historial_panel}

TRABAJA SOBRE EL TEXTO ORIGINAL DE ARRIBA: ese es el texto REAL del estudiante (ya indexado). Tu \
`texto_mejorado` es la versión REESCRITA de SU texto, NO un ejemplo genérico de muestra. Si hay texto \
original, NUNCA digas «no tengo acceso a tu texto» ni inventes uno de ejemplo: mejora el que tienes.

PRESERVA EL CONTENIDO REAL DEL ESTUDIANTE: mejora la REDACCIÓN, la estructura y la completitud, NUNCA \
la SUSTANCIA. No cambies sus variables ni sus nombres, no inventes variables/dimensiones/indicadores \
nuevos ni reemplaces los suyos (p. ej. si su variable dependiente es «Calidad metodológica», NO la \
cambies por otra). CONSERVA sus CITAS, autores, datos y factores específicos (p. ej. si cita a «Jiménez \
(2023)» o menciona «la sobrecarga docente», MANTENLOS tal cual); NUNCA los reemplaces por afirmaciones \
genéricas ni los borres. EDITA su texto (no escribas uno nuevo desde cero, no lo resumas). Si algo le \
falta para cumplir la rúbrica, complétalo de forma coherente con SU proyecto; si no hay base en el texto, \
dilo en `recomendaciones` en vez de inventarlo.

ÁMBITO: es un PROYECTO de investigación (propuesta), NO una tesis terminada: aún NO hay resultados, \
discusión ni conclusiones. No agregues ni pidas esas secciones.

OPERACIONALIZACIÓN DE VARIABLES: NUNCA la entregues como tabla (es ancha y se rompe en el chat) ni copies \
la tabla cruda del PDF (con tabulaciones). Preséntala SIEMPRE como LISTA con viñetas anidadas, MISMO formato \
para TODAS las variables: «- **Variable independiente: <nombre>**» y debajo «- Definición conceptual: …», \
«- Definición operacional: …», «- Dimensiones: …», «- Indicadores: …», «- Ítems: …», «- Escala de medición: …»; \
igual para la dependiente. No dejes una variable en tabla y otra en lista.

Devuelve DOS campos separados:
- `texto_mejorado`: la versión mejorada de SOLO el fragmento pedido, lista para entregar (sin notas \
dentro). Si la consulta NO pedía reescribir texto (p. ej. solo pidió lineamientos), deja este campo vacío.
- `recomendaciones`: lo que NO va dentro del texto (incongruencias con el enfoque, coherencia con otras \
secciones), como sugerencias accionables. Vacío si no hay nada que observar."""

_PROMPT_ESTRUCTURADOR = """\
Eres MentorIA, un mentor metodológico que acompaña a un estudiante de tesis en un chat. Un análisis \
interno ya preparó la mejora de su consulta; tu tarea es entregar UNA respuesta de chat clara, cálida \
y bien estructurada en español y markdown.

Incluye, cuando aporten valor:
1. Una explicación breve de qué mejorar y por qué.
2. El TEXTO MEJORADO en un bloque claro, presentado como la versión mejorada de SU texto (titúlalo \
«Tu <sección> mejorado/a»). NUNCA lo presentes como «un ejemplo de cómo podrías estructurarlo» ni «aquí \
tienes un ejemplo»: es SU texto reescrito, no un molde genérico.
3. LINEAMIENTOS concretos para alcanzar el MÁXIMO puntaje según la rúbrica.

REGLAS:
- NO menciones el mecanismo interno (no hables de «agentes», «panel» ni «debate»): responde como un mentor.
- NO inventes citas ni autores. Sigue el hilo de la conversación.
- El estudiante YA subió su proyecto (lo tienes indexado; el material de abajo es SUYO). NUNCA le pidas \
compartir, pegar ni subir su texto: trabaja con el MATERIAL DEL ANÁLISIS. Si ahí hay TEXTO MEJORADO, \
entrégalo; nunca respondas «comparte tu texto».
- ÁMBITO: es un PROYECTO de investigación (propuesta), NO una tesis terminada: aún NO tiene resultados, \
discusión ni conclusiones. No ofrezcas ayuda con «resultados» ni «conclusiones» que todavía no existen.
- Si te piden EVALUAR o CALIFICAR (poner nota), aclara que para eso la red de agentes hará la revisión \
formal (máxima precisión, pero toma más tiempo); que te lo pida con «evalúa…». Tú aquí orientas y mejoras rápido.
- Sé directo y conciso.

MATERIAL DEL ANÁLISIS INTERNO:
- TEXTO MEJORADO (puede estar vacío):
{texto_sintetizado}

- RECOMENDACIONES:
{recomendaciones}

- CRITERIOS DE LA RÚBRICA RELEVANTES:
{criterios_rubrica}

- SÍNTESIS DEL ANÁLISIS:
{historial_panel}
"""


# ── Nodos del grafo (cada uno: lógica secuencial interna) ────────────────────

def _nodo_recuperacion(state: EstadoDebate) -> dict:
    from .conversador import _recuperar_libros, _estado_proyecto
    from .rubrica_chat import criterios_relevantes

    doc = state.get("doc")
    biblioteca = state.get("biblioteca")
    consulta = state.get("consulta", "")

    libros, _fuente = _recuperar_libros(biblioteca, consulta)
    criterios, seccion = criterios_relevantes(doc, consulta)

    # COHERENCIA con el grafo grande: si ya hay un TEXTO CORREGIDO de esta sección (de una
    # revisión previa o de una mejora del chat), parte de ÉL — no del original — para no
    # reinventar ni contradecir lo que la red grande ya decidió.
    tesis = ""
    base_corregida = ""
    if doc is not None and seccion:
        m = (getattr(doc, "mejoras", None) or {}).get(seccion)
        if m and m.get("texto"):
            base_corregida = m["texto"]

    if base_corregida:
        tesis = base_corregida
        logger.info(f"[debate_rapido] Partiendo del texto corregido de «{seccion}» (coherencia con la red).")
    elif doc is not None and getattr(doc, "vector_store", None) is not None:
        from backend.rag import recuperar_con_vecinos, limpiar_marcas_rag
        try:
            crudo = recuperar_con_vecinos(
                doc.vector_store, consulta, seccion=seccion, k=5, ventana=1
            )
            tesis = limpiar_marcas_rag(crudo)
        except Exception as exc:
            logger.warning(f"[debate_rapido] RAG tesis con vecinos falló: {exc}")

    enfoque = ""
    estado = _estado_proyecto(doc)
    if doc is not None:
        try:
            from .tipo_investigacion import obtener_tipo_diseno
            from backend.enfoque import bloque_enfoque
            tipo, diseno = obtener_tipo_diseno(doc)
            enfoque = bloque_enfoque(tipo, diseno)
        except Exception as exc:
            logger.warning(f"[debate_rapido] No se pudo detectar el tipo: {exc}")

    logger.info(
        f"[debate_rapido] Recuperación lista | sección: {seccion or '—'} | "
        f"rúbrica: {'sí' if criterios else 'no'} | tesis: {len(tesis)} chars"
    )
    return {
        "contexto_libros": libros or "(sin fragmentos de libros recuperados)",
        "contexto_tesis": tesis or "(sin fragmentos de la tesis — o el proyecto no está cargado)",
        "criterios_rubrica": criterios or "(el estudiante no cargó una rúbrica; usa criterios metodológicos estándar)",
        "seccion": seccion or "",
        "enfoque": enfoque,
        "estado_proyecto": estado,
        "debate_memory": [],
    }


def _nodo_rigor(state: EstadoDebate) -> dict:
    from backend.enfoque import especialista_metodologico
    from .tipo_investigacion import obtener_tipo_diseno

    doc = state.get("doc")
    tipo = "cuantitativa"
    if doc is not None and getattr(doc, "tipo_investigacion", None):
        tipo = doc.tipo_investigacion

    chain = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_RIGOR),
        ("human", "Emite tu análisis de rigor del fragmento bajo mejora."),
    ]) | llm_rapido(temperatura=0.2)

    inputs = {
        "especialista": especialista_metodologico(tipo),
        "enfoque": state.get("enfoque", ""),
        "consulta": state.get("consulta", ""),
        "contexto_tesis": state.get("contexto_tesis", ""),
        "criterios_rubrica": state.get("criterios_rubrica", ""),
        "contexto_libros": state.get("contexto_libros", ""),
    }
    memoria = list(state.get("debate_memory") or [])
    try:
        contenido = _invocar(chain, inputs)
    except Exception as exc:
        logger.warning(f"[debate_rapido/rigor] Falló: {exc}")
        contenido = "[El metodólogo de rigor no pudo intervenir.]"
    memoria.append({"agente": "metodologo_rigor", "contenido": contenido})
    return {"debate_memory": memoria}


def _nodo_coherencia(state: EstadoDebate) -> dict:
    chain = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_COHERENCIA),
        ("human", "Responde al metodólogo de rigor y emite tu análisis de coherencia."),
    ]) | llm_rapido(temperatura=0.3)

    memoria = list(state.get("debate_memory") or [])
    inputs = {
        "enfoque": state.get("enfoque", ""),
        "consulta": state.get("consulta", ""),
        "contexto_tesis": state.get("contexto_tesis", ""),
        "criterios_rubrica": state.get("criterios_rubrica", ""),
        "contexto_libros": state.get("contexto_libros", ""),
        "historial_panel": _formatear_memoria(memoria),
    }
    try:
        contenido = _invocar(chain, inputs)
    except Exception as exc:
        logger.warning(f"[debate_rapido/coherencia] Falló: {exc}")
        contenido = "[El metodólogo de coherencia no pudo intervenir.]"
    memoria.append({"agente": "metodologo_coherencia", "contenido": contenido})
    return {"debate_memory": memoria}


def _nodo_sintetizador(state: EstadoDebate) -> dict:
    chain = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_SINTETIZADOR),
        ("human", "Resuelve el debate y entrega el texto mejorado y las recomendaciones."),
    ]) | llm_rapido(temperatura=0.3).with_structured_output(SintesisDebate)

    inputs = {
        "enfoque": state.get("enfoque", ""),
        "consulta": state.get("consulta", ""),
        "contexto_tesis": state.get("contexto_tesis", ""),
        "criterios_rubrica": state.get("criterios_rubrica", ""),
        "historial_panel": _formatear_memoria(state.get("debate_memory") or []),
    }
    try:
        out = _invocar(chain, inputs)
        texto = (out.texto_mejorado or "").strip()
        recs = (out.recomendaciones or "").strip()
    except Exception as exc:
        logger.warning(f"[debate_rapido/sintetizador] Falló: {exc}")
        texto, recs = "", ""
    return {"texto_sintetizado": texto, "recomendaciones": recs}


def _nodo_estructurador(state: EstadoDebate) -> dict:
    from .conversador import _historial_a_mensajes

    sistema = _PROMPT_ESTRUCTURADOR.format(
        texto_sintetizado=state.get("texto_sintetizado") or "(no se reescribió texto)",
        recomendaciones=state.get("recomendaciones") or "(sin recomendaciones)",
        criterios_rubrica=state.get("criterios_rubrica", ""),
        historial_panel=_formatear_memoria(state.get("debate_memory") or []),
    )
    mensajes = [SystemMessage(content=sistema)]
    mensajes.extend(_historial_a_mensajes(state.get("historial") or []))
    mensajes.append(HumanMessage(content=state.get("consulta", "")))

    try:
        respuesta = llm_rapido(temperatura=0.3).invoke(mensajes).content.strip()
    except Exception as exc:
        logger.error(f"[debate_rapido/estructurador] Falló: {exc}")
        # Degradación: si hay texto sintetizado, devuélvelo crudo.
        respuesta = state.get("texto_sintetizado") or _FALLBACK
    return {"respuesta_final": respuesta}


def _invocar(chain, inputs):
    """Invoca la cadena con los reintentos de backoff compartidos del proyecto."""
    from backend.graph.nodes._utils import invocar_con_backoff
    salida = invocar_con_backoff(chain, inputs)
    if isinstance(salida, SintesisDebate):
        return salida
    return salida.content.strip() if hasattr(salida, "content") else str(salida).strip()


# ── Construcción del grafo (una sola vez) ────────────────────────────────────

def _construir_grafo():
    g = StateGraph(EstadoDebate)
    g.add_node("recuperacion", _nodo_recuperacion)
    g.add_node("metodologo_rigor", _nodo_rigor)
    g.add_node("metodologo_coherencia", _nodo_coherencia)
    g.add_node("sintetizador", _nodo_sintetizador)
    g.add_node("estructurador", _nodo_estructurador)

    g.set_entry_point("recuperacion")
    g.add_edge("recuperacion", "metodologo_rigor")
    g.add_edge("metodologo_rigor", "metodologo_coherencia")
    g.add_edge("metodologo_coherencia", "sintetizador")
    g.add_edge("sintetizador", "estructurador")
    g.add_edge("estructurador", END)
    return g.compile()


_GRAFO = _construir_grafo()


def responder_mejora_rapida(
    mensaje: str,
    historial: list[dict],
    doc,
    biblioteca,
) -> dict:
    """Punto de entrada: corre el mini-grafo de debate.

    Devuelve `{"respuesta", "seccion", "texto_mejorado"}`. `seccion` y `texto_mejorado`
    permiten al API guardar la mejora como pendiente (para evaluarla luego con la red).
    """
    estado_inicial: EstadoDebate = {
        "consulta": mensaje,
        "historial": historial or [],
        "doc": doc,
        "biblioteca": biblioteca,
    }
    try:
        final = _GRAFO.invoke(estado_inicial)
    except Exception as exc:
        logger.error(f"[debate_rapido] Error ejecutando el grafo: {exc}")
        return {"respuesta": _FALLBACK, "seccion": None, "texto_mejorado": ""}

    return {
        "respuesta": (final.get("respuesta_final") or "").strip() or _FALLBACK,
        "seccion": (final.get("seccion") or "") or None,
        "texto_mejorado": (final.get("texto_sintetizado") or "").strip(),
    }
