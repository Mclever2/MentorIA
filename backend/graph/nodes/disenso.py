"""
Nodo Disenso — Panel de 2 subagentes especializados con LoRA.

¿POR QUÉ 2 SUBAGENTES Y NO MÁS?
  El disenso tiene 2 dimensiones distintas de conflicto:
    1. Conflictos explícitos: contradicciones directas y verificables entre evaluadores
    2. Conflictos estructurales: tensiones de fondo, prioridades incompatibles, desacuerdos implícitos

  Un 3er subagente buscaría conflictos en un espacio que los otros 2 ya cubren completamente.
  2 es el número correcto para este agente.

SUBAGENTES:
  1. disenso_explicito (temp 0.20)
     LoRA: detector de contradicciones directas
     MCP:  ninguno (trabaja solo con el feedback del Auditor y Metodólogo del estado)
     → ¿El Auditor y el Metodólogo se contradicen directamente en algo verificable?

  2. disenso_estructural (temp 0.30)
     LoRA: analista de tensiones de fondo
     MCP:  ninguno
     → Lee lo que reportó Sub1 y busca el conflicto más profundo:
       ¿Tienen prioridades diferentes? ¿Criterios incompatibles con este tipo de trabajo?

DEBATE CON MEMORIA COMPARTIDA:
  Sub2 (estructural) recibe el reporte de Sub1 (explícito) via historial_panel
  y lo profundiza, evitando repetir lo obvio.
  El resultado final es la CONCATENACIÓN de ambos análisis.
"""

import logging
import os

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from ..state import MentoriaState
from ._utils import cargar_prompt, invocar_con_backoff
from ._panel_utils import ejecutar_panel, consolidar_panel_texto, ResultadoSubagente

logger = logging.getLogger(__name__)


def make_nodo_disenso(llm: ChatOpenAI):
    """
    Construye el Nodo Disenso con panel de 2 subagentes (LoRA).
    """
    prompt_base = cargar_prompt("disenso_prompt.md")
    model_name  = getattr(llm, "model_name", "gpt-4o-mini")

    def nodo_disenso(state: MentoriaState) -> dict:
        n_iter    = state.get("numero_iteracion", 1)
        seccion   = state["seccion_objetivo"]
        n_errores = len(state.get("errores_rubrica") or [])
        universidad = state.get("universidad", "upao")
        programa    = state.get("programa", "ingeniería de sistemas")

        logger.info(
            f"[Disenso] Iteración #{n_iter} | Errores={n_errores} | {seccion} | "
            f"Panel: explícito + estructural"
        )

        texto_actual = state.get("texto_iterado") or state.get("contexto_recuperado", "")

        inputs_base = {
            "seccion":                     seccion,
            "numero_iteracion":            n_iter,
            "n_errores":                   n_errores,
            "feedback_auditor":            state.get("feedback_auditor") or "Sin feedback del Auditor.",
            "observaciones_metodologicas": state.get("observaciones_metodologicas") or "Sin observaciones del Metodólogo.",
            "texto_iterado":               texto_actual,
            "errores_rubrica":             str(state.get("errores_rubrica") or []),
            "resultado_consenso":          state.get("resultado_consenso") or "",
            "universidad":                 universidad,
            "programa":                    programa,
        }

        from backend.lora.lora_configs import get_loras_para_agente, TIPO_DISENSO
        from backend.mcp.tools import crear_fetch_para_lora

        loras = get_loras_para_agente(
            TIPO_DISENSO, universidad, programa,
            perfil_override=state.get("perfil_institucional"),
        )

        sub_items = []

        for idx, lora in enumerate(loras):
            sub_llm = ChatOpenAI(
                api_key=os.getenv("OPENAI_API_KEY", ""),
                model=model_name,
                temperature=lora.temperatura,
                max_retries=3,
                timeout=600.0,
            )

            system_prompt = lora.system_prompt_completo(prompt_base)

            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", (
                    "Analiza los conflictos entre el Auditor y el Metodólogo "
                    "en la evaluación de la sección '{seccion}'.\n\n"
                    "**ANÁLISIS DE CONFLICTOS PREVIO EN ESTE PANEL:**\n"
                    "{historial_panel}\n\n"
                    "Proporciona tu análisis de disenso desde tu perspectiva especializada."
                )),
            ])
            chain = prompt | sub_llm

            mcp_fn = crear_fetch_para_lora(lora.fuentes_datos, lora.drive_folder_id)
            sub_items.append((chain, lora.id, mcp_fn))

        resultados = ejecutar_panel(sub_items, inputs_base, logger_prefix="Disenso")

        if not any(r.exitoso for r in resultados):
            logger.warning("[Disenso] Panel falló — usando LLM base como fallback")
            prompt_fb = ChatPromptTemplate.from_messages([
                ("system", prompt_base),
                ("human", "Analiza las evaluaciones y produce el análisis de disenso."),
            ])
            chain_fb = prompt_fb | llm
            output_fb = invocar_con_backoff(chain_fb, inputs_base)
            resultados = [ResultadoSubagente(lora_id="fallback", output=output_fb)]

        resultado_disenso = consolidar_panel_texto(resultados)

        loras_usadas = [lora.id for lora in loras]
        logger.info(
            f"[Disenso] Análisis completo ({len(resultado_disenso)} chars) | "
            f"LoRAs: {loras_usadas}"
        )

        return {
            "resultado_disenso": resultado_disenso,
            "iter_disenso":      n_iter + 1,
            "loras_activas":     loras_usadas,
            "disenso_ejecutado":  True,
        }

    return nodo_disenso
