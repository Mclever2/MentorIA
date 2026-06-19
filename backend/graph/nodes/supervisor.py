"""
Agente Supervisor Orquestador — Corazón de la red multiagente.

En la arquitectura de RED PURA, este nodo es el único que decide el flujo.
El LLM analiza el estado completo y elige el siguiente agente a ejecutar.
Si el LLM falla o devuelve un valor inválido, se aplica un fallback determinista.

Flujo:
  START → supervisor → [redactor | auditor | metodologico | debate | consenso | disenso | fin]
              ↑______________________________________________|
  (todos los agentes regresan al supervisor tras su ejecución)

Protección anti-bucle infinito:
  - pasos_ejecutados se incrementa en cada llamada al supervisor
  - Si pasos_ejecutados >= max_pasos_red → fuerza "fin" sin llamar al LLM
  - Capa adicional: recursion_limit en workflow.py
"""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from ..state import MentoriaState
from ._utils import cargar_prompt, invocar_con_backoff
from config import Config

logger = logging.getLogger(__name__)

NODOS_VALIDOS = {
    "auditor", "metodologico", "consenso", "disenso",
    "debate", "redactor", "fin"
}

_META_DEFECTO = 0.90


def _meta_alcanzada(state: MentoriaState) -> bool:
    """True si el puntaje del auditor ya llegó a la meta (% del máximo)."""
    pmax = state.get("_puntaje_max") or 0
    pest = state.get("puntaje_estimado")
    meta = state.get("meta_aprobacion") or _META_DEFECTO
    return bool(pmax) and pest is not None and (float(pest) / float(pmax)) >= meta


def _estancado(state: MentoriaState) -> bool:
    """True si la última iteración del redactor NO mejoró el puntaje (no vale gastar otra)."""
    n_iter = state.get("numero_iteracion", 0)
    prev   = state.get("puntaje_previo")
    cur    = state.get("puntaje_estimado")
    return n_iter >= 1 and prev is not None and cur is not None and float(cur) <= float(prev)


def _fallback_routing(state: MentoriaState) -> str:
    """
    Fallback determinista SOLO si el LLM falla o devuelve valor inválido.
    Este es el último recurso, no el camino normal.
    """
    n_iter        = state.get("numero_iteracion", 0)
    max_iter      = state.get("max_iteraciones", 3)
    n_errores     = len(state.get("errores_rubrica") or [])
    pasos         = state.get("pasos_ejecutados", 0)
    max_pasos     = state.get("max_pasos_red") or Config.get_max_pasos(max_iter)

    if pasos >= max_pasos:
        return "fin"
    if not state.get("auditor_ejecutado", False):
        return "auditor"
    if not state.get("metodologo_ejecutado", False):
        return "metodologico"

    # Consenso, disenso y debate SOLO aportan cuando hay errores que consolidar,
    # cuestionar o debatir. Sin errores, el panel ya coincidió en que la sección
    # está limpia: se ahorran esas llamadas y se pasa directo al redactor/fin.
    if n_errores > 0:
        if not state.get("consenso_ejecutado", False):
            return "consenso"
        if not state.get("disenso_ejecutado", False):
            return "disenso"
        if not state.get("debate_ejecutado", False) and n_iter < max_iter:
            return "debate"
        if state.get("texto_iterado") is None or n_iter < max_iter:
            return "redactor"
        return "fin"

    # Sin errores: no se ejecutan consenso/disenso/debate.
    if not state.get("texto_iterado"):
        return "redactor"  # al menos una pasada (pulido) para dar sugerencias
    if _meta_alcanzada(state) or n_iter >= max_iter or _estancado(state):
        return "fin"
    return "redactor"


def _validar_decision_semantica(siguiente: str, state: MentoriaState) -> str | None:
    """
    Valida que la decisión del LLM sea semánticamente coherente con el estado.
    Retorna None si es válida, o un string con el motivo del rechazo si no lo es.
    """
    n_iter    = state.get("numero_iteracion", 0)
    max_iter  = state.get("max_iteraciones", 3)
    n_errores = len(state.get("errores_rubrica") or [])

    auditor_ok      = state.get("auditor_ejecutado", False)
    metodologico_ok = state.get("metodologo_ejecutado", False)
    consenso_ok     = state.get("consenso_ejecutado", False)
    disenso_ok      = state.get("disenso_ejecutado", False)
    debate_completado = state.get("debate_ejecutado", False)

    if n_iter >= max_iter and state.get("texto_iterado") and siguiente != "fin":
        if siguiente == "auditor" and not auditor_ok:
            return None
        return f"ciclo completo (iter {n_iter}/{max_iter}) con texto generado — debe ser fin"

    if siguiente == "fin":
        if not auditor_ok:
            return "fin sin auditor ejecutado"
        if n_errores > 0 and n_iter < max_iter:
            return f"fin con {n_errores} errores y {max_iter - n_iter} iteraciones restantes"
        # No terminar si aún no se llega a la meta y quedan iteraciones (y el
        # redactor todavía está mejorando): hay que cerrar la brecha.
        if (not _meta_alcanzada(state) and n_iter < max_iter
                and not _estancado(state) and state.get("texto_iterado")):
            return "fin sin alcanzar la meta con iteraciones restantes"
        # Siempre al menos una pasada del redactor (aunque el original ya esté en meta:
        # corre el pulidor para dar sugerencias al estudiante).
        if not state.get("texto_iterado"):
            return "fin sin pasada del redactor"

    # Sin errores, consenso/disenso no aportan → el redactor puede correr sin ellos.
    if siguiente == "redactor" and n_errores > 0:
        if not consenso_ok:
            return "redactor sin consenso ejecutado"
        if not disenso_ok:
            return "redactor sin disenso ejecutado"

    if siguiente in ("consenso", "disenso") and n_errores == 0:
        return f"{siguiente} innecesario sin errores (panel sin hallazgos)"

    if siguiente == "consenso" and (not auditor_ok or not metodologico_ok):
        return "consenso sin auditor y metodólogo completos"

    if siguiente == "disenso" and (not auditor_ok or not metodologico_ok):
        return "disenso sin auditor y metodólogo completos"

    if siguiente == "debate" and n_errores == 0:
        return "debate sin errores activos"

    if siguiente == "debate" and debate_completado:
        return "debate ya ejecutado en esta iteración — ir a redactor"

    return None


def make_nodo_supervisor(llm: ChatOpenAI):
    """
    Fábrica del Supervisor Orquestador.

    Devuelve un nodo que:
      1. Verifica el límite de pasos (anti-bucle)
      2. Llama al LLM con el estado completo para decidir el siguiente nodo
      3. Valida la respuesta y aplica fallback si es inválida
      4. Retorna la decisión de routing + actualizaciones de estado
    """
    plantilla = cargar_prompt("supervisor_red_prompt.md")

    prompt = ChatPromptTemplate.from_messages([
        ("system", plantilla),
        ("human", "Decide el siguiente nodo."),
    ])
    chain = prompt | llm

    def nodo_supervisor(state: MentoriaState) -> dict:
        pasos     = state.get("pasos_ejecutados", 0)
        n_iter    = state.get("numero_iteracion", 0)
        max_iter  = state.get("max_iteraciones", 3)
        max_pasos = state.get("max_pasos_red") or Config.get_max_pasos(max_iter)
        n_errores = len(state.get("errores_rubrica") or [])

        auditor_ok      = state.get("auditor_ejecutado", False)
        metodologico_ok = state.get("metodologo_ejecutado", False)
        consenso_ok     = state.get("consenso_ejecutado", False)
        disenso_ok      = state.get("disenso_ejecutado", False)
        debate_completado = state.get("debate_ejecutado", False)

        logger.info(
            f"[Supervisor] Paso {pasos + 1}/{max_pasos} | "
            f"Iter {n_iter}/{max_iter} | Errores={n_errores} | "
            f"Aud={'✓' if auditor_ok else '✗'} Met={'✓' if metodologico_ok else '✗'} "
            f"Debate={'✓' if debate_completado else '✗'}"
        )

        if pasos >= max_pasos:
            logger.warning(f"[Supervisor] Límite de pasos ({pasos}/{max_pasos}) → fin")
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": f"Límite de pasos alcanzado ({pasos}). Fin forzado.",
                "plan_supervisor":          "[FIN] Límite de pasos alcanzado",
                "pasos_ejecutados":         pasos + 1,
            }

        # MODO NÚCLEO: no se re-audita tras el redactor. Su nota NO es una calificación
        # real (esa sale del barrido por ítem), y el redactor entrega un texto PARCIAL
        # (solo los subpuntos reescritos + observaciones); re-auditarlo bajaría el
        # puntaje de forma engañosa (p. ej. 15 → 7). Tras la pasada del redactor → fin.
        if state.get("modo_nucleo") and n_iter >= 1 and state.get("texto_iterado"):
            logger.info("[Supervisor] Modo núcleo: redactor ya entregó la mejora → fin (sin re-auditar)")
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": "Núcleo: mejora entregada; no se re-audita el texto parcial.",
                "plan_supervisor":          "[FIN] Núcleo",
                "pasos_ejecutados":         pasos + 1,
            }

        if n_iter >= max_iter and state.get("texto_iterado") and auditor_ok:
            logger.info(
                f"[Supervisor] Ciclo completo: iter {n_iter}/{max_iter} con texto generado y auditado → fin"
            )
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": f"Ciclo {n_iter}/{max_iter} completado con texto mejorado y auditado.",
                "plan_supervisor":          "[FIN] Ciclo completado",
                "pasos_ejecutados":         pasos + 1,
            }

        # Si el redactor SOLO pulió (texto sin cambios), re-auditar es inútil:
        # la sección ya estaba en la meta → terminar tras dar las sugerencias.
        if state.get("redactor_solo_pulido") and state.get("texto_iterado"):
            logger.info("[Supervisor] Redactor solo pulió (texto en la meta) → fin")
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": "Sección ya en la meta; el redactor entregó sugerencias de pulido.",
                "plan_supervisor":          "[FIN] Pulido",
                "pasos_ejecutados":         pasos + 1,
            }

        # Early-stop por META: si el panel terminó, ya hubo al menos una pasada del
        # redactor y se llegó al objetivo, no gastes más iteraciones.
        if auditor_ok and consenso_ok and disenso_ok and state.get("texto_iterado") and _meta_alcanzada(state):
            logger.info(
                f"[Supervisor] Meta alcanzada "
                f"({state.get('puntaje_estimado')}/{state.get('_puntaje_max')}) → fin anticipado"
            )
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": "Meta de puntaje alcanzada — no se requieren más iteraciones.",
                "plan_supervisor":          "[FIN] Meta alcanzada",
                "pasos_ejecutados":         pasos + 1,
            }

        # Anti-estancamiento: si la última iteración del redactor no subió el
        # puntaje, otra iteración tampoco ayudará → terminar.
        if auditor_ok and consenso_ok and disenso_ok and state.get("texto_iterado") and _estancado(state):
            logger.info(
                f"[Supervisor] Sin mejora vs. iteración previa "
                f"({state.get('puntaje_previo')} → {state.get('puntaje_estimado')}) → fin"
            )
            return {
                "siguiente_nodo":           "fin",
                "instrucciones_supervisor": "El redactor no mejoró el puntaje respecto a la iteración previa — fin.",
                "plan_supervisor":          "[FIN] Sin mejora",
                "pasos_ejecutados":         pasos + 1,
            }

        llm_input = {
            "seccion":             state.get("seccion_objetivo", ""),
            "numero_iteracion":    n_iter,
            "max_iteraciones":     max_iter,
            "auditor_ok":          auditor_ok,
            "metodologico_ok":     metodologico_ok,
            "consenso_ok":         consenso_ok,
            "disenso_ok":          disenso_ok,
            "n_errores":           n_errores,
            "debate_completado":   debate_completado,
            "puntaje_estimado":    state.get("puntaje_estimado"),
            "tiene_texto_iterado": bool(state.get("texto_iterado")),
        }

        try:
            respuesta = invocar_con_backoff(chain, llm_input)
            siguiente = respuesta.content.strip().lower().strip(".,;:")
            if siguiente not in NODOS_VALIDOS:
                logger.warning(f"[Supervisor] LLM devolvió '{siguiente}' inválido → fallback")
                siguiente = _fallback_routing(state)
            else:
                motivo_rechazo = _validar_decision_semantica(siguiente, state)
                if motivo_rechazo:
                    logger.debug(
                        f"[Supervisor] LLM dijo '{siguiente}' → inválido "
                        f"({motivo_rechazo}) → fallback determinista"
                    )
                    siguiente = _fallback_routing(state)
                else:
                    logger.info(f"[Supervisor] LLM decidió → {siguiente}")
        except Exception as exc:
            logger.warning(f"[Supervisor] LLM falló ({exc}) → fallback")
            siguiente = _fallback_routing(state)

        extra = {
            "debate_completado": False,
            "debate_memory":     [],
            "consenso_ejecutado": False,
            "disenso_ejecutado": False,
            "auditor_ejecutado": False,
            "metodologo_ejecutado": False,
            "debate_ejecutado": False,
        } if siguiente == "redactor" else {}

        return {
            "siguiente_nodo":           siguiente,
            "instrucciones_supervisor": f"LLM → {siguiente}",
            "plan_supervisor":          f"[{siguiente.upper()}] decisión LLM",
            "pasos_ejecutados":         pasos + 1,
            **extra,
        }

    return nodo_supervisor
