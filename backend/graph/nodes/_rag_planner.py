"""
Planificador de contexto RAG dinámico para los agentes evaluadores.

Flujo de cada agente que lo usa:
  1. El agente lee la sección objetivo (ya en state["contexto_recuperado"])
  2. Este módulo hace UNA llamada LLM para decidir qué secciones adicionales buscar
  3. Ejecuta esas queries contra el vector store activo (rag_context.py)
  4. Devuelve el contexto enriquecido para inyectarlo en inputs_base

Por qué una llamada de planificación y no tool calling directo:
  Groq no permite bind_tools + with_structured_output simultáneamente de forma
  limpia. La separación en dos fases (planificación libre → evaluación estructurada)
  es compatible con todos los modelos y evita conflictos de output schema.
"""

from __future__ import annotations

import logging
import time

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from backend.rag.rag_context import get_vector_store, buscar_fragmentos

logger = logging.getLogger(__name__)

_PAUSA_POST_PLANIFICACION = 0.3

_PROMPT_PLANNER = """\
Eres un Planificador de Contexto RAG Académico (rol: {rol}).
Estás evaluando la sección "{seccion}" de un proyecto de tesis de Ingeniería de la UPAO.

CRITERIOS DE LA RÚBRICA A EVALUAR:
{criterios}

OBSERVACIONES/FEEDBACK DEL AUDITOR:
{feedback_auditor}

Tu tarea es decidir qué otras secciones del PDF de tesis o qué información específica necesitas consultar de la memoria RAG para resolver las observaciones del Auditor, verificar consistencia o enriquecer la redacción.

Devuelve EXACTAMENTE 2 o 3 queries de búsqueda en español, una por línea, sin numeración ni explicaciones adicionales. Cada query debe ser concisa (4-8 palabras) y directa para buscar en ChromaDB.

Ejemplos de queries:
antecedentes internacionales calidad metodologica
objetivos especificos investigacion
operacionalizacion variable independiente
poblacion muestra calculo estadistico
"""


def obtener_contexto_dinamico(
    llm: ChatOpenAI,
    seccion: str,
    texto_snippet: str,
    rol: str,
    criterios: str = "",
    feedback_auditor: str = "",
    k_por_query: int = 4,
) -> str:
    """
    Hace UNA llamada LLM para planificar qué buscar, luego ejecuta las queries.

    Args:
        llm:              Instancia ChatGroq del agente (usa su propia API key).
        seccion:          Nombre de la sección bajo evaluación.
        texto_snippet:    Extracto del texto a evaluar (primeros ~400 chars).
        rol:              Descripción del rol del agente (para el prompt).
        criterios:        Criterios de la rúbrica aplicables a esta sección.
        feedback_auditor: Observaciones y feedback del auditor para resolver errores.
        k_por_query:      Fragmentos a recuperar por cada query.

    Returns:
        Contexto adicional recuperado (string con fragmentos etiquetados),
        o "" si el vector store no está disponible o la planificación falla.
    """
    if get_vector_store() is None:
        logger.info(f"[RAGPlanner/{rol}] Vector store no disponible — sin enriquecimiento")
        return ""

    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _PROMPT_PLANNER),
            ("human", "Extracto del texto actual a mejorar:\n{texto}"),
        ])
        respuesta = (prompt | llm).invoke({
            "rol":              rol,
            "seccion":          seccion,
            "criterios":        criterios or "Sin criterios específicos.",
            "feedback_auditor": feedback_auditor or "Sin observaciones previas.",
            "texto":            texto_snippet[:400],
        })
        lineas = [l.strip() for l in respuesta.content.strip().split("\n") if l.strip()]
        queries = lineas[:3]
        logger.info(f"[RAGPlanner/{rol}] Queries planificadas: {queries}")
    except Exception as exc:
        logger.warning(f"[RAGPlanner/{rol}] Falló la planificación: {exc}")
        return ""

    time.sleep(_PAUSA_POST_PLANIFICACION)

    # Excluir la UNIDAD de evaluación completa (prefijo de rúbrica), no solo la
    # hoja: lo que ya está en el contexto principal no debe repetirse aquí, pero
    # las secciones hermanas relevantes sí deben poder aparecer.
    from backend.config import prefijos_evaluacion_para_seccion
    prefijos_excluidos = [
        p for p in (prefijos_evaluacion_para_seccion(seccion)
                    or [_extraer_prefijo_numerico(seccion)])
        if p
    ]
    partes: list[str] = []
    vistas: set[str] = set()

    for query in queries:
        resultado = buscar_fragmentos(query, k=k_por_query)
        if not resultado:
            continue

        fragmentos_filtrados = _filtrar_seccion_principal(resultado, prefijos_excluidos, vistas)
        if fragmentos_filtrados:
            partes.append(f"**[Contexto buscado: {query}]**\n{fragmentos_filtrados}")

    if not partes:
        logger.info(f"[RAGPlanner/{rol}] Sin contexto adicional recuperado")
        return ""

    contexto = "\n\n---\n\n".join(partes)
    logger.info(
        f"[RAGPlanner/{rol}] Contexto dinámico: {len(partes)} bloques, "
        f"{len(contexto)} chars totales"
    )
    return contexto



def _extraer_prefijo_numerico(seccion: str) -> str:
    """Extrae el prefijo numérico de una sección: '2.1. Título' → '2.1'"""
    import re
    m = re.match(r'^(\d[\d\.]*)', seccion.strip())
    return m.group(1).rstrip('.') if m else ""


def _filtrar_seccion_principal(
    resultado: str,
    prefijos_excluidos: list[str],
    vistas: set[str],
) -> str:
    """
    Del resultado de buscar_fragmentos, descarta los fragmentos que
    pertenecen a la unidad de evaluación (ya en contexto_recuperado) o
    ya fueron incluidos en una query anterior.

    `prefijos_excluidos` es la lista de prefijos de la unidad de evaluación
    (p.ej. ['1.2'] o ['4.1','4.2','4.3']).
    """
    import re

    partes_filtradas = []
    for bloque in resultado.split("\n\n"):
        if not bloque.strip():
            continue

        m = re.match(r'^\[(\d+)\s*[—-]\s*([^\]]+)\]', bloque)
        seccion_bloque = m.group(2).strip() if m else ""
        prefijo_bloque = _extraer_prefijo_numerico(seccion_bloque)

        if prefijo_bloque and any(
            prefijo_bloque == pe or prefijo_bloque.startswith(pe + ".")
            for pe in prefijos_excluidos
        ):
            continue

        clave = prefijo_bloque or seccion_bloque[:30]
        if clave and clave in vistas:
            continue
        if clave:
            vistas.add(clave)

        partes_filtradas.append(bloque)

    return "\n\n".join(partes_filtradas)
