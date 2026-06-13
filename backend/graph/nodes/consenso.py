"""
Nodo Consenso — Identifica acuerdos entre Auditor y Metodólogo.

CAMBIO 5: añade consenso matemático determinístico.
  - calcular_consenso_matematico() decide si hay consenso (sin LLM).
  - El LLM solo genera la narrativa explicativa.
  - consenso_matematico["activar_debate"] guía al Supervisor.
"""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from ..state import MentoriaState
from ._utils import cargar_prompt, invocar_con_backoff, calcular_consenso_matematico

logger = logging.getLogger(__name__)


def make_nodo_consenso(llm: ChatOpenAI):
    plantilla = cargar_prompt("consenso_prompt.md")
    prompt    = ChatPromptTemplate.from_messages([
        ("system", plantilla),
        ("human",  "Analiza las evaluaciones y produce el análisis de consenso."),
    ])
    chain = prompt | llm

    def nodo_consenso(state: MentoriaState) -> dict:
        n_iter  = state.get("numero_iteracion", 1)
        seccion = state["seccion_objetivo"]
        logger.info(f"[Consenso] Iteración #{n_iter} | {seccion}")

        texto_actual = state.get("texto_iterado") or state.get("contexto_recuperado", "")

        puntaje_auditor     = float(state.get("puntaje_estimado") or 0.0)
        puntaje_metodologico = float(state.get("puntaje_estimado") or 0.0)
        scores_raw = state.get("scores_subagentes") or []
        if not scores_raw:
            scores_raw = [puntaje_auditor]

        consenso_mat = calcular_consenso_matematico(scores_raw, umbral_std=0.5)
        logger.info(
            f"[Consenso] Matemático: hay_consenso={consenso_mat['hay_consenso']} "
            f"| {consenso_mat['motivo']}"
        )

        respuesta = invocar_con_backoff(chain, {
            "seccion":                     seccion,
            "numero_iteracion":            n_iter,
            "feedback_auditor":            state.get("feedback_auditor") or "Sin feedback del Auditor.",
            "observaciones_metodologicas": state.get("observaciones_metodologicas") or "Sin observaciones del Metodólogo.",
            "texto_iterado":               texto_actual,
        })

        resultado = respuesta.content.strip()
        logger.info(f"[Consenso] Narrativa completada ({len(resultado)} chars)")

        return {
            "resultado_consenso": resultado,
            "iter_consenso":      n_iter + 1,
            "consenso_matematico": consenso_mat,
            "consenso_ejecutado": True,
        }

    return nodo_consenso
