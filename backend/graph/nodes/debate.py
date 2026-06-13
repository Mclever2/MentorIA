"""
Nodo Debate — Panel de 4 subagentes con memoria compartida.

Reemplaza los nodos debate_auditor y debate_metodologo.
Los 4 subagentes comparten debate_memory (lista de dicts acumulada) y
corren secuencialmente: cada uno lee el historial completo antes de escribir.

Flujo interno:
  perspectiva_formal → perspectiva_metodologica → perspectiva_contextual → sintetizador_debate

El sintetizador emite un veredicto estructurado (confirmado/descartado/matizado por ítem)
y actualiza errores_rubrica eliminando los ítems descartados.
"""

import logging
import time
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ..state import MentoriaState, ErrorRubrica
from ._utils import invocar_con_backoff

logger = logging.getLogger(__name__)

_PAUSA_ENTRE_SUBS = 3.0



class VeredictoPanelDebate(BaseModel):
    items_confirmados: List[int] = Field(
        description="Números de ítems de rúbrica confirmados como errores reales (≥2/3 perspectivas)"
    )
    items_descartados: List[int] = Field(
        description="Números de ítems descartados — no son errores reales (≥2/3 perspectivas)"
    )
    items_matizados: List[int] = Field(
        description="Números de ítems matizados — contradicción entre perspectivas, se mantienen con menor peso"
    )
    justificacion: str = Field(
        description="Justificación narrativa del veredicto (2-4 oraciones)"
    )
    veredicto_general: str = Field(
        description="'confirmado' si la mayoría de errores persisten, 'descartado' si la mayoría se eliminan, 'matizado' si hay empate o contradicción fundamental"
    )



_PROMPT_FORMAL = """\
Eres un evaluador institucional especializado en la rúbrica oficial UPAO.
Analiza si los errores identificados por el auditor son válidos según los criterios formales de la rúbrica.
Basa tu argumento exclusivamente en los ítems de la rúbrica y las normas institucionales.

CONTEXTO DEL DEBATE:
- Sección evaluada: {seccion}
- Errores bajo debate (ítems): {errores_rubrica}
- Feedback del auditor: {feedback_auditor}
- Observaciones metodológicas: {observaciones_metodologicas}

EVALUACIONES PREVIAS EN ESTE PANEL:
{historial_panel}

Analiza cada ítem de error desde la perspectiva formal-institucional UPAO.
¿Son válidos según la rúbrica? ¿Hay base normativa para cada uno?
Emite tu postura por ítem, siendo preciso y basándote en la rúbrica."""

_PROMPT_METODOLOGICO = """\
Eres un metodólogo científico experto en investigación universitaria.
Estás participando en un debate estructurado sobre errores detectados en una tesis.

El evaluador formal ya emitió su postura. DEBES responder directamente a su argumento
antes de agregar tu análisis propio. No puedes ignorar lo que dijo.

CONTEXTO DEL DEBATE:
- Sección evaluada: {seccion}
- Errores bajo debate (ítems): {errores_rubrica}
- Feedback del auditor: {feedback_auditor}
- Observaciones metodológicas: {observaciones_metodologicas}

POSTURA DEL EVALUADOR FORMAL (responde a esto):
{historial_panel}

Tu respuesta debe tener esta estructura obligatoria:

REACCIÓN AL EVALUADOR FORMAL:
[Para cada ítem que él analizó: ¿coincides o discrepas? Argumenta con rigor científico.
Si la rúbrica dice que es error pero el método no lo respalda, dilo explícitamente.
Si coincides, di por qué el método confirma su criterio formal.]

MI ANÁLISIS METODOLÓGICO ADICIONAL:
[Aspectos de rigor científico que el evaluador formal no consideró, si los hay.]

Puedes discrepar de la rúbrica institucional si el método científico lo justifica.
Sé directo: "discrepo con el evaluador formal en el ítem N porque..." o
"confirmo la postura del evaluador formal en el ítem N porque..."\
"""

_PROMPT_CONTEXTUAL = """\
Eres un evaluador contextual especializado en investigación de ingeniería
en universidades peruanas. Estás participando en un debate estructurado.

Los evaluadores formal y metodológico ya emitieron sus posturas y pueden haber
discrepado entre sí. DEBES tomar posición respecto a ambos antes de dar la tuya.

CONTEXTO DEL DEBATE:
- Sección evaluada: {seccion}
- Errores bajo debate (ítems): {errores_rubrica}
- Feedback del auditor: {feedback_auditor}
- Observaciones metodológicas: {observaciones_metodologicas}

POSTURAS DE LOS EVALUADORES ANTERIORES (toma posición respecto a cada una):
{historial_panel}

Tu respuesta debe tener esta estructura obligatoria:

REACCIÓN AL EVALUADOR FORMAL:
[¿Su criterio de rúbrica aplica en el contexto real de UPAO? ¿O la rúbrica
es más exigente que lo que la institución realmente valida en la práctica?]

REACCIÓN AL EVALUADOR METODOLÓGICO:
[¿Su análisis de rigor científico es apropiado para el nivel de pregrado
en ingeniería en Perú? ¿O exige un estándar que no corresponde al contexto?]

MI POSTURA CONTEXTUAL:
[Tu veredicto final por ítem considerando ambas posturas anteriores y el
contexto universitario peruano. Indica explícitamente si apoyas al formal,
al metodológico, o tienes una posición distinta a ambos, y por qué.]

Sé directo: "apoyo al evaluador formal sobre el ítem N", "discrepo con ambos
evaluadores en el ítem N porque en UPAO..."\
"""

_PROMPT_SINTETIZADOR = """\
Eres el árbitro final de un debate entre tres evaluadores especializados.
Tu rol no es evaluar la tesis — es resolver el debate analizando los argumentos
y contrargumentos que se dieron, y aplicar la regla de mayoría informada.

CONTEXTO DEL DEBATE:
- Sección evaluada: {seccion}
- Ítems bajo debate: {errores_rubrica}

TRANSCRIPCIÓN COMPLETA DEL DEBATE (los 3 evaluadores con sus reacciones mutuas):
{historial_panel}

Para cada ítem de error debes:
1. Identificar si hubo acuerdo, desacuerdo o posición mixta entre los evaluadores
2. Determinar qué argumento fue más sólido considerando el debate completo
3. Aplicar la regla: ≥2/3 confirman → confirmado | ≥2/3 descartan → descartado | empate → matizado

REGLAS:
- Si el metodológico y el contextual refutaron al formal con argumentos sólidos → descartado
  aunque el formal haya dicho que es error
- Si hubo debate real y ninguno convenció a los otros → matizado
- Si los tres coincidieron a pesar de partir de perspectivas distintas → confirmado con alta confianza
- No cuentes votos mecánicamente — pesa la calidad del argumento, no solo la posición

Emite el veredicto estructurado con justificación que explique qué argumentos
del debate fueron determinantes para cada ítem.\
"""


def make_nodo_debate(llm_auditor: ChatOpenAI, llm_metodologico: ChatOpenAI):
    """Fábrica del nodo debate unificado con panel de 4 subagentes."""

    chain_formal = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_FORMAL),
        ("human", "Emite tu análisis formal de los errores bajo debate."),
    ]) | llm_auditor

    chain_metodologica = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_METODOLOGICO),
        ("human", "Emite tu análisis metodológico de los errores bajo debate."),
    ]) | llm_metodologico

    chain_contextual = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_CONTEXTUAL),
        ("human", "Emite tu análisis contextual de los errores bajo debate."),
    ]) | llm_metodologico

    chain_sintetizador = ChatPromptTemplate.from_messages([
        ("system", _PROMPT_SINTETIZADOR),
        ("human", "Emite el veredicto estructurado del panel."),
    ]) | llm_metodologico.with_structured_output(VeredictoPanelDebate)

    subagentes = [
        ("perspectiva_formal",        chain_formal),
        ("perspectiva_metodologica",  chain_metodologica),
        ("perspectiva_contextual",    chain_contextual),
        ("sintetizador_debate",       chain_sintetizador),
    ]

    def nodo_debate(state: MentoriaState) -> dict:
        seccion    = state.get("seccion_objetivo", "")
        errores:   List[ErrorRubrica] = state.get("errores_rubrica") or []
        n_errores  = len(errores)

        logger.info(
            f"[Debate] Iniciando panel de 4 subagentes | "
            f"Sección: {seccion} | Errores activos: {n_errores}"
        )

        if n_errores == 0:
            logger.warning("[Debate] Sin errores activos — panel omitido")
            return {
                "debate_completado": True,
                "debate_veredicto":  {"veredicto_general": "sin_errores", "justificacion": "No había errores activos"},
                "debate_memory":     [],
            }

        inputs_base = {
            "seccion":                    seccion,
            "errores_rubrica":            _formatear_errores(errores),
            "feedback_auditor":           state.get("feedback_auditor", ""),
            "observaciones_metodologicas": state.get("observaciones_metodologicas", ""),
        }

        debate_memory: list = []
        exitosos = 0
        veredicto_raw: Optional[VeredictoPanelDebate] = None

        for nombre, chain in subagentes:
            inputs = dict(inputs_base)
            inputs["historial_panel"] = _formatear_historial(debate_memory) if debate_memory else \
                "Eres el primer evaluador del panel — no hay evaluaciones anteriores que considerar."

            if exitosos > 0:
                time.sleep(_PAUSA_ENTRE_SUBS)

            try:
                output = invocar_con_backoff(chain, inputs)

                if hasattr(output, "content"):
                    contenido = output.content.strip()
                elif isinstance(output, VeredictoPanelDebate):
                    contenido = (
                        f"Veredicto — Confirmados: {output.items_confirmados} | "
                        f"Descartados: {output.items_descartados} | "
                        f"Matizados: {output.items_matizados}\n"
                        f"Justificación: {output.justificacion}"
                    )
                    veredicto_raw = output
                else:
                    contenido = str(output).strip()

                debate_memory.append({"subagente": nombre, "contenido": contenido})
                exitosos += 1
                logger.info(f"[Debate/{nombre}] ✓ completado")

            except Exception as exc:
                logger.warning(f"[Debate/{nombre}] Falló: {exc}")
                debate_memory.append({
                    "subagente": nombre,
                    "contenido": f"[Error — no disponible: {exc}]",
                })

        logger.info(f"[Debate] Panel completo: {exitosos}/4 subagentes")

        if veredicto_raw is None:
            logger.warning("[Debate] Sintetizador sin output — todos los errores se mantienen")
            veredicto_dict = {
                "items_confirmados": [e["item_numero"] for e in errores],
                "items_descartados": [],
                "items_matizados":   [],
                "justificacion":     "El sintetizador no pudo emitir veredicto — errores conservados por precaución.",
                "veredicto_general": "confirmado",
            }
            items_descartados_set: set = set()
        else:
            items_descartados_set = set(veredicto_raw.items_descartados)
            veredicto_dict = {
                "items_confirmados": list(veredicto_raw.items_confirmados),
                "items_descartados": list(veredicto_raw.items_descartados),
                "items_matizados":   list(veredicto_raw.items_matizados),
                "justificacion":     veredicto_raw.justificacion,
                "veredicto_general": veredicto_raw.veredicto_general,
            }

        errores_actualizados = [
            e for e in errores
            if e["item_numero"] not in items_descartados_set
        ]

        veredicto_general = veredicto_dict.get("veredicto_general", "confirmado")
        logger.info(
            f"[Debate] Panel completo: {exitosos}/4 | "
            f"veredicto: {veredicto_general} | "
            f"errores_activos: {len(errores_actualizados)} "
            f"({len(items_descartados_set)} descartados)"
        )

        historial = list(state.get("historial_debate") or [])
        historial.append({
            "tipo":     "panel",
            "panel":    debate_memory,
            "veredicto": veredicto_dict,
        })

        return {
            "debate_memory":     debate_memory,
            "debate_veredicto":  veredicto_dict,
            "debate_completado": True,
            "errores_rubrica":   errores_actualizados,
            "historial_debate":  historial,
            "debate_ejecutado":  True,
        }

    return nodo_debate



def _formatear_errores(errores: list) -> str:
    if not errores:
        return "(sin errores activos)"
    lineas = []
    for e in errores:
        if isinstance(e, dict):
            lineas.append(
                f"  - Ítem {e.get('item_numero', '?')} "
                f"(puntaje={e.get('puntaje_actual', '?')}): {e.get('descripcion', '')}"
            )
        else:
            lineas.append(f"  - {e}")
    return "\n".join(lineas)


def _formatear_historial(debate_memory: list) -> str:
    partes = []
    for entrada in debate_memory:
        nombre = entrada.get("subagente", "?")
        contenido = entrada.get("contenido", "")
        partes.append(f"[{nombre}]\n{contenido}")
    return "\n\n".join(partes)
