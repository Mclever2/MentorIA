"""
Nodo Redactor — 3 subagentes según el puntaje de la sección.

1. Si el puntaje es > 90% del máximo posible:
   - Se utiliza únicamente el Subagente 3 (Pulidor / Recomendador).
   - Este subagente genera recomendaciones de pulido finas. No reescribe el texto.
   
2. Si el puntaje es <= 90% del máximo posible:
   - Se utilizan el Subagente 1 (Escritor) y el Subagente 2 (Evaluador de Rúbrica).
   - Subagente 1 (Escritor): reescribe y mejora el texto base.
   - Subagente 2 (Evaluador): identifica y muestra las secciones de la rúbrica metodológica
     especializada que fueron tomadas en cuenta para calificar el texto de entrada.
"""

import logging
import os

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from ..state import MentoriaState
from ._utils import invocar_con_backoff
from ._rag_planner import obtener_contexto_dinamico
from evaluator.metrics.llm_judge import evaluar_con_juez_llm

logger = logging.getLogger(__name__)

_UMBRAL_EXCELENCIA = 0.90

_PROMPT_ESCRITOR = """
Eres un asesor académico experto en redacción de tesis de pregrado en Ingeniería.
Tu tarea es reescribir y mejorar la sección de tesis del estudiante, aplicando las correcciones de los errores confirmados por el panel de auditoría, las observaciones metodológicas y el feedback general.

REGLAS DE ESCRITURA OBLIGATORIAS:
- **Usa el contexto RAG**: Incorpora datos empíricos, antecedentes, referencias a estudios previos, o información de otras secciones del proyecto que aparezcan en el contexto RAG para corregir los vacíos señalados (por ejemplo, si el Auditor observa la falta de antecedentes, incorpóralos usando la información real presente en el contexto RAG de la tesis).
- Mantén el registro académico formal. Si es necesario para cumplir con los antecedentes o la descripción empírica solicitada por el Auditor, expande el texto lo necesario para que sea completo y riguroso.
- Si no hay datos específicos en el RAG para completar un vacío (ej. estadísticas del problema), usa marcadores explicativos como `[INSERTAR DATO ESTADÍSTICO ACÁ]` o redacta de forma cualitativa con base en la realidad del proyecto.
- Para OBJETIVOS GENERALES: redacta UNA sola oración con esta estructura:
  [verbo infinitivo] + [variable independiente] + "en" + [variable dependiente] + "de" + [unidad de análisis] + "en" + [horizonte temporal].
  No añadas sub-dimensiones, instrumentos ni metodología dentro del objetivo general.
- Para OBJETIVOS ESPECÍFICOS: cada uno debe ser una oración independiente que se derive lógicamente del objetivo general.

FORMATO DE RESPUESTA:
Responde ÚNICAMENTE con el texto mejorado, respetando la numeración y estructura de la sección, sin introducciones, saludos ni explicaciones adicionales.
"""

_PROMPT_PULIDOR = """
Eres un asesor académico experto en tesis de Ingeniería de pregrado.
La sección del estudiante ya ha alcanzado una calidad excelente (>90% de la rúbrica).
Tu tarea es recomendar únicamente mejoras de estilo muy específicas, detalles que pulir o pequeños ajustes para alcanzar la perfección.
NO reescribas el texto completo, ya que el estudiante conservará su propia redacción.

FORMATO DE SALIDA OBLIGATORIO:

ESTADO DE LA SECCIÓN: Excelente — lista para entregar

RECOMENDACIONES DE PULIDO:
1. Descripción exacta: qué detalle de estilo, puntuación, claridad o concordancia pulir, y en qué parte exacta del texto.
2. ...

VEREDICTO: LISTA PARA ENTREGAR
"""

def make_nodo_redactor(llm: ChatOpenAI):
    """Construye el Nodo Redactor con 3 subagentes."""
    model_name = getattr(llm, "model_name", "gpt-4o-mini")

    def nodo_redactor(state: MentoriaState) -> dict:
        iteracion_actual = state.get("numero_iteracion", 0) + 1
        universidad      = state.get("universidad", "upao")
        programa         = state.get("programa", "ingeniería de sistemas")
        seccion          = state["seccion_objetivo"]
        texto_base       = state.get("texto_iterado") or state["contexto_recuperado"]

        historial_textos = list(state.get("historial_textos") or [])
        if not historial_textos:
            historial_textos.append(state.get("contexto_recuperado") or "")

        puntaje_estimado = float(state.get("puntaje_estimado") or 0.0)
        puntaje_max      = float(state.get("_puntaje_max") or 0.0)
        porcentaje       = (puntaje_estimado / puntaje_max) if puntaje_max > 0 else 0.0
        supera_umbral    = porcentaje > _UMBRAL_EXCELENCIA

        logger.info(
            f"[Redactor] Iteración #{iteracion_actual} | {seccion} | "
            f"Puntaje: {puntaje_estimado}/{puntaje_max} ({porcentaje:.0%}) | "
            f"Modo: {'PULIDOR (Sub3)' if supera_umbral else 'ESCRITURA (Sub1+Sub2)'}"
        )

        if supera_umbral:
            prompt_pul = ChatPromptTemplate.from_messages([
                ("system", _PROMPT_PULIDOR),
                ("human", (
                    "Sección evaluada: **{seccion}** (iteración #{iteracion})\n\n"
                    "**PUNTAJE:** {puntaje_estimado}/{puntaje_max} ({porcentaje})\n\n"
                    "**FEEDBACK DEL AUDITOR:**\n{feedback_auditor}\n\n"
                    "**TEXTO ACTUAL DEL ESTUDIANTE:**\n{texto_actual}\n\n"
                    "Genera las recomendaciones de pulido."
                )),
            ])
            chain_pul = prompt_pul | llm

            try:
                output = invocar_con_backoff(chain_pul, {
                    "seccion":            seccion,
                    "iteracion":          iteracion_actual,
                    "puntaje_estimado":   int(puntaje_estimado),
                    "puntaje_max":        int(puntaje_max),
                    "porcentaje":         f"{porcentaje:.0%}",
                    "feedback_auditor":   state.get("feedback_auditor") or "Sin feedback específico.",
                    "texto_actual":       texto_base,
                })
                sugerencias_texto = output.content.strip()
            except Exception as exc:
                logger.warning(f"[Redactor/Pulidor] Falló: {exc} — usando fallback")
                sugerencias_texto = (
                    f"Sección aprobada con excelente puntuación ({porcentaje:.0%}). "
                    f"No hay recomendaciones de pulido adicionales."
                )

            texto_final = texto_base
            historial_textos.append(texto_final)

            return {
                "texto_iterado":                 texto_final,
                "numero_iteracion":              iteracion_actual,
                "loras_activas":                 ["redactor_pulidor"],
                "redactor_sugerencias_mejoras":  sugerencias_texto,
                "redactor_evaluacion_rubrica":   None,
                "historial_textos":              historial_textos,
            }

        
        evaluacion_rubrica_dict = None


        logger.info("[Redactor] Subagente 1 ejecutando reescritura del texto...")
        
        from backend.config import _buscar_items_seccion, RUBRICA_ITEMS_UPAO
        items_nums = _buscar_items_seccion(seccion)
        criterios_lista = [f"- Ítem {n}: {RUBRICA_ITEMS_UPAO.get(n)}" for n in items_nums]
        criterios_str = "\n".join(criterios_lista)

        contexto_dinamico = obtener_contexto_dinamico(
            llm              = llm,
            seccion          = seccion,
            texto_snippet    = texto_base[:500],
            rol              = "redactor académico que mejora secciones de tesis de ingeniería",
            criterios        = criterios_str,
            feedback_auditor = state.get("feedback_auditor") or state.get("observaciones_metodologicas") or "",
        )

        historial_debate_lista = state.get("historial_debate") or []
        if historial_debate_lista:
            ultima = historial_debate_lista[-1]
            confirmados = ultima.get("items_confirmados", [])
            descartados = ultima.get("items_descartados", [])
            veredicto_debate = (
                f"Tras {len(historial_debate_lista)} ronda(s) de debate:\n"
                f"- Ítems confirmados como errores reales: {confirmados}\n"
                f"- Ítems descartados: {descartados}"
            )
        else:
            veredicto_debate = "No hubo debate previo en esta iteración."

        inputs_base = {
            "seccion":                  seccion,
            "iteracion":                iteracion_actual,
            "max_iteraciones":          state.get("max_iteraciones", 3),
            "contexto_recuperado":      state["contexto_recuperado"],
            "contexto_dependencias":    contexto_dinamico or state.get("contexto_dependencias") or "Sin contexto de secciones relacionadas.",
            "contexto_teorico":         state.get("contexto_teorico") or "",
            "texto_actual":             texto_base,
            "plan_supervisor":          state.get("plan_supervisor") or "Sin plan previo.",
            "feedback_auditor":         state.get("feedback_auditor") or "Primera iteración.",
            "observaciones_metodologicas": state.get("observaciones_metodologicas") or "",
            "veredicto_debate":         veredicto_debate,
            "errores_confirmados":      _formatear_errores(state.get("errores_rubrica") or []),
            "universidad":              universidad,
            "programa":                 programa,
            "contexto_secciones_relacionadas": "",
        }

        prompt_esc = ChatPromptTemplate.from_messages([
            ("system", _PROMPT_ESCRITOR),
            ("human", (
                "Genera la versión mejorada del texto para la sección **{seccion}** (iteración #{iteracion}).\n\n"
                "**TEXTO ORIGINAL:**\n{texto_actual}\n\n"
                "**ERRORES CONFIRMADOS POR EL PANEL:**\n{errores_confirmados}\n\n"
                "**FEEDBACK METODOLÓGICO:**\n{observaciones_metodologicas}\n\n"
                "**CONTEXTO RAG DE LIBROS:**\n{contexto_teorico}\n\n"
                "**CONTEXTO DE OTRAS SECCIONES:**\n{contexto_dependencias}\n\n"
                "Responde únicamente con el texto mejorado."
            )),
        ])
        chain_esc = prompt_esc | llm

        try:
            output_esc = invocar_con_backoff(chain_esc, inputs_base)
            texto_final = output_esc.content.strip()
        except Exception as exc:
            logger.warning(f"[Redactor/Escritor] Falló: {exc} — usando fallback")
            texto_final = texto_base

        historial_textos.append(texto_final)

        return {
            "texto_iterado":                 texto_final,
            "numero_iteracion":              iteracion_actual,
            "loras_activas":                 ["redactor_escritor", "redactor_evaluador"],
            "redactor_sugerencias_mejoras":  None,
            "redactor_evaluacion_rubrica":   evaluacion_rubrica_dict,
            "historial_textos":              historial_textos,
        }

    return nodo_redactor

def _formatear_errores(errores: list) -> str:
    """Formatea la lista de errores confirmados para el prompt del redactor."""
    if not errores:
        return "No hay errores específicos confirmados — revisa el feedback general del Auditor."
    lineas = []
    for e in errores:
        if isinstance(e, dict):
            lineas.append(
                f"- Ítem {e.get('item_numero', '?')}: {e.get('descripcion', '')} "
                f"(puntaje actual: {e.get('puntaje_actual', '?')}/3)"
            )
    return "\n".join(lineas) if lineas else "Sin errores específicos."
