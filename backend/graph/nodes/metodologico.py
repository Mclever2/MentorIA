"""
Nodo Metodólogo — Panel de 2 subagentes especializados con LoRA + MCP.

¿POR QUÉ 2 SUBAGENTES Y NO MÁS?
  El metodólogo tiene exactamente 2 responsabilidades distintas:
    1. Validar el rigor científico (diseño, método, operacionalización)
    2. Verificar la coherencia transversal (consistencia entre secciones)
  Añadir un 3ro solaparía con uno de estos — no hay una 3ra dimensión genuina.
  2 es el número correcto para este agente.

SUBAGENTES:
  1. metodologo_rigor (temp 0.10)
     LoRA: especialista en validación científica
     MCP:  Biblioteca (libros Hernández Sampieri, Creswell, etc.) + Drive institucional
     → ¿El diseño de investigación es correcto? ¿Los métodos son apropiados?

  2. metodologo_coherencia (temp 0.20)
     LoRA: especialista en coherencia cruzada de secciones
     MCP:  Tesis (secciones relacionadas del documento)
     → Lee lo que dijo Sub1 + verifica consistencia entre capítulos

DEBATE CON MEMORIA COMPARTIDA:
  Sub2 (coherencia) recibe el análisis de Sub1 (rigor) via historial_panel
  y puede confirmar, matizar o complementar desde su perspectiva.
  El resultado final es la CONCATENACIÓN de ambos análisis —
  no hay score numérico por ítem, así que no aplica consenso matemático.
"""

import logging
import os

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from ..state import MentoriaState
from ._utils import cargar_prompt, invocar_con_backoff
from ._rag_planner import obtener_contexto_dinamico
from ._panel_utils import ejecutar_panel, consolidar_panel_texto, ResultadoSubagente

logger = logging.getLogger(__name__)


def make_nodo_metodologico(llm: ChatOpenAI):
    """
    Construye el Nodo Metodólogo con panel de 2 subagentes (LoRA + MCP).
    """
    prompt_base = cargar_prompt("metodologico_prompt.md")
    model_name  = getattr(llm, "model_name", "llama-3.3-70b-versatile")
    api_key_base = (
        os.getenv("GROQ_KEY_METODOLOGICO") or os.getenv("GROQ_API_KEY", "")
    )

    def nodo_metodologico(state: MentoriaState) -> dict:
        logger.info("[Metodólogo] Iniciando panel de 2 subagentes (LoRA + MCP)...")

        seccion     = state["seccion_objetivo"]
        n_iter      = state.get("numero_iteracion", 0)
        universidad = state.get("universidad", "upao")
        programa    = state.get("programa", "ingeniería de sistemas")

        texto_a_evaluar = state.get("texto_iterado") or state.get("contexto_recuperado", "")
        fuente_texto    = "mejorado" if state.get("texto_iterado") else "original del PDF"

        logger.info(
            f"[Metodólogo] Ciclo {n_iter} | {seccion} | {fuente_texto} | "
            f"Universidad: {universidad}"
        )

        from ._rubrica import criterios_para_seccion
        crit = criterios_para_seccion(state, seccion)
        criterios_str = crit["criterios_str"]

        from backend.enfoque import bloque_enfoque, especialista_metodologico
        tipo_inv = state.get("tipo_investigacion")
        enfoque = bloque_enfoque(tipo_inv, state.get("diseno"))

        # Paquete de coherencia: reusa lo que ya planificó el auditor en esta
        # iteración en vez de gastar otra llamada de planificación RAG.
        contexto_dinamico = state.get("contexto_coherencia")
        if contexto_dinamico:
            logger.info("[Metodólogo] Reusando paquete de coherencia del auditor (sin RAG extra)")
        else:
            logger.info("[Metodólogo] Planificando contexto adicional con RAG dinámico…")
            contexto_dinamico = obtener_contexto_dinamico(
                llm              = llm,
                seccion          = seccion,
                texto_snippet    = texto_a_evaluar[:500],
                rol              = "metodólogo experto en coherencia cruzada de tesis universitarias",
                criterios        = criterios_str,
                feedback_auditor = "",
            )

        inputs_base = {
            "seccion":                  seccion,
            "texto_iterado":            texto_a_evaluar,
            "contexto_dependencias":    contexto_dinamico or state.get("contexto_dependencias") or "Sin contexto de secciones relacionadas.",
            "contexto_recuperado":      state.get("contexto_recuperado", ""),
            "contexto_teorico":         state.get("contexto_teorico") or "",
            "numero_iteracion":         n_iter,
            "universidad":              universidad,
            "programa":                 programa,
            "rubrica_institucional_drive":       "",
            "contexto_biblioteca_disponible":    "",
            "contexto_secciones_relacionadas":   "",
            "enfoque":                           enfoque,
        }

        from backend.lora.lora_configs import get_loras_para_agente, TIPO_METODOLOGO
        from backend.mcp.tools import crear_fetch_para_lora

        loras = get_loras_para_agente(
            TIPO_METODOLOGO, universidad, programa,
            perfil_override=state.get("perfil_institucional"),
        )

        # Híbrido: el 1er subagente (rigor) se especializa según el tipo de
        # investigación detectado; el 2do (coherencia) valida la trazabilidad.
        if loras:
            loras[0].prompt_modificador = especialista_metodologico(tipo_inv)

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
                    "{enfoque}\n\n"
                    "Evalúa el rigor metodológico de la sección '{seccion}' "
                    "(iteración {numero_iteracion}). Verifica la TRAZABILIDAD: que el tipo y el "
                    "diseño declarados concuerden entre sí y con el contenido; señala incongruencias "
                    "(p. ej. hipótesis estadísticas en un estudio cualitativo, u operacionalización "
                    "donde no corresponde) y adecúa tus recomendaciones al enfoque.\n\n"
                    "**PERSPECTIVAS DE EVALUADORES ANTERIORES DEL PANEL:**\n"
                    "{historial_panel}\n\n"
                    "{contexto_biblioteca_disponible}\n\n"
                    "{contexto_secciones_relacionadas}"
                )),
            ])
            chain = prompt | sub_llm

            mcp_fn = crear_fetch_para_lora(lora.fuentes_datos, lora.drive_folder_id)
            sub_items.append((chain, lora.id, mcp_fn))

        resultados = ejecutar_panel(sub_items, inputs_base, logger_prefix="Metodólogo")

        if not any(r.exitoso for r in resultados):
            logger.warning("[Metodólogo] Panel falló — usando LLM base como fallback")
            prompt_fb = ChatPromptTemplate.from_messages([
                ("system", prompt_base),
                ("human", "Evalúa el rigor metodológico de la sección '{seccion}'."),
            ])
            chain_fb = prompt_fb | llm
            output_fb = invocar_con_backoff(chain_fb, inputs_base)
            resultados = [ResultadoSubagente(lora_id="fallback", output=output_fb)]

        observaciones = consolidar_panel_texto(
            resultados,
            separador="\n\n---\n\n",
        )

        loras_usadas = [lora.id for lora in loras]

        logger.info(
            f"[Metodólogo] Evaluación completa ({len(observaciones)} chars) | "
            f"LoRAs: {loras_usadas}"
        )

        return {
            "observaciones_metodologicas": observaciones,
            "iter_metodologica":           n_iter + 1,
            "loras_activas":               loras_usadas,
            "metodologo_ejecutado":        True,
        }

    return nodo_metodologico


