"""
Nodo Redactor — 2 modos según el puntaje de la sección.

1. Si el puntaje es > 90% del máximo posible → modo PULIDO (Pulidor):
   - El texto ya está bien; NO se reescribe ni se cambia estructura/contenido.
   - Se aplican solo retoques FINOS (puntuación, tildes, claridad, palabra exacta) y se
     devuelve el texto pulido + la lista de qué se retocó (en las recomendaciones).

2. Si el puntaje es <= 90% del máximo posible → modo ESCRITURA (Escritor):
   - Reescribe y mejora el texto base, cerrando la brecha hacia la meta de la rúbrica.
   - Devuelve `texto_redactado` (limpio, calificable) + `recomendaciones` (lo que no debe
     forzarse en el texto: incongruencias de enfoque/diseño, coherencia con otras secciones).

Nota: la EVALUACIÓN contra la rúbrica la realiza el nodo Auditor, no el redactor.
"""

import logging
import os

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ..state import MentoriaState
from ._utils import invocar_con_backoff
from ._rag_planner import obtener_contexto_dinamico
from evaluator.metrics.llm_judge import evaluar_con_juez_llm

logger = logging.getLogger(__name__)

_UMBRAL_EXCELENCIA = 0.90


class RedaccionSeccion(BaseModel):
    """Dos entregables separados del Subagente Escritor.

    Solo `texto_redactado` se califica (auditor + juez LLM). Las `recomendaciones`
    orientan al estudiante pero NO se evalúan, por eso van fuera del texto.
    """
    texto_redactado: str = Field(
        description=(
            "Versión mejorada de SOLO la sección pedida, lista para entregar. "
            "Sin avisos, notas ni advertencias dentro: solo el texto de la tesis."
        )
    )
    recomendaciones: str = Field(
        default="",
        description=(
            "Observaciones que NO van dentro del texto: incongruencias con el enfoque/diseño, "
            "problemas metodológicos o de coherencia con otras secciones, redactadas como "
            "sugerencias accionables. Cadena vacía si no hay nada que observar."
        ),
    )

_PROMPT_ESCRITOR = """
Eres un asesor académico experto en redacción de tesis de pregrado en Ingeniería.
Tu tarea tiene DOS entregables SEPARADOS para la sección indicada:

1) `texto_redactado`: la versión mejorada de **solo la sección pedida**, lista para entregar.
2) `recomendaciones`: observaciones que NO van dentro del texto (incongruencias, problemas
   metodológicos o de coherencia con otras secciones), redactadas como sugerencias.

POR QUÉ SEPARADOS: lo único que se califica es `texto_redactado`. Las `recomendaciones`
orientan al estudiante pero no se evalúan, así que NUNCA mezcles avisos, notas, advertencias
ni «(sugerencia: …)» dentro de `texto_redactado`.

REGLAS PARA `texto_redactado`:
- Respeta el ENFOQUE del proyecto (tipo y diseño). NO impongas estructuras de otro enfoque.
- NO FUERCES elementos que el tipo/diseño no requiere:
  * No agregues hipótesis si el enfoque no las exige, ni hipótesis a un objetivo específico que no las necesita.
  * Si el diseño pide hipótesis cuantitativas Y cualitativas y solo hay de un tipo, NO inventes las faltantes dentro del texto.
  * Si el tipo no contempla operacionalización de variables (p. ej. cualitativa, tecnológica), no la agregues.
- Si el estudiante TIENE algo que NO corresponde a su enfoque (p. ej. hipótesis estadísticas en
  un estudio cualitativo, hipótesis en un objetivo específico que no las requiere), NO lo borres
  ni lo "arregles" a la fuerza dentro del texto: déjalo y explica el problema en `recomendaciones`.
- Usa el contexto RAG para corregir vacíos REALES señalados por el panel (antecedentes, datos,
  referencias de otras secciones del proyecto). Si falta un dato, usa marcadores como
  `[INSERTAR DATO ESTADÍSTICO ACÁ]` o redacta de forma cualitativa con base en la realidad del proyecto.
- Mantén el registro académico formal y respeta la numeración y estructura de la sección.
- TABLAS (p. ej. operacionalización de variables): el texto se muestra en un chat, así que las
  tablas complejas se ven mal. Si necesitas presentar una tabla:
  * Hazla en Markdown GFM VÁLIDO y SIMPLE: una fila por línea, fila de encabezado seguida de la
    fila separadora `|---|---|`, y NUNCA dejes celdas vacías para simular celdas combinadas
    (repite el valor de la variable/dimensión en cada fila que lo necesite).
  * Si la tabla tendría muchas columnas o sería muy ancha, NO uses tabla: preséntala como una
    LISTA con viñetas anidadas (una viñeta por variable y sub-viñetas con sus campos).
- Solo si el enfoque es CUANTITATIVO, para el OBJETIVO GENERAL usa la forma:
  [verbo infinitivo] + [variable independiente] + "en" + [variable dependiente] + "de" +
  [unidad de análisis] + "en" + [horizonte temporal]; los específicos derivan de él, cada uno en
  una oración independiente. Para OTROS enfoques, respeta la forma propia de su tipo y NO impongas
  variables ni medición que su enfoque no contempla.

REGLAS PARA `recomendaciones`:
- Español, como sugerencias accionables (no como texto de tesis).
- Aquí va lo que NO cuadra con el enfoque/diseño, las incongruencias de trazabilidad señaladas por
  el metodólogo y cualquier problema de coherencia con otras secciones.
- Si no hay nada que observar, deja la cadena vacía.
"""

_PROMPT_PULIDOR = """
Eres un asesor académico experto en tesis de Ingeniería de pregrado.
La sección del estudiante YA alcanzó una calidad excelente (>90% de la rúbrica): su contenido,
estructura, argumentos, datos y enfoque son correctos. NO la reescribas: NO cambies su estructura,
ideas, argumentos, datos ni significado, ni expandas el texto.

Tu tarea es aplicar ÚNICAMENTE retoques FINOS de FORMA: puntuación, tildes/ortografía,
concordancia, claridad de alguna frase puntual o una palabra más precisa. Cambios mínimos y
locales, jamás estructurales ni de contenido.

Devuelve DOS campos:
- `texto_redactado`: la MISMA sección con esos retoques mínimos ya aplicados (si no hay nada que
  retocar, devuélvela idéntica). Solo el texto de la tesis, sin notas ni marcas dentro.
- `recomendaciones`: en español, di que el texto YA estaba correcto y LISTA exactamente qué
  retoques aplicaste y dónde (p. ej. «coma añadida tras "…"», «tilde en "análisis"»,
  «se precisó "hacer" por "implementar"»). Si no aplicaste ninguno, dilo explícitamente.
"""

def make_nodo_redactor(llm: ChatOpenAI):
    """Construye el Nodo Redactor con 3 subagentes."""
    model_name = getattr(llm, "model_name", "gpt-4o-mini")

    def nodo_redactor(state: MentoriaState) -> dict:
        iteracion_actual = state.get("numero_iteracion", 0) + 1
        universidad      = state.get("universidad", "upao")
        programa         = state.get("programa", "ingeniería de sistemas")
        seccion          = state["seccion_objetivo"]
        modo_nucleo      = bool(state.get("modo_nucleo"))
        from backend.rag import limpiar_marcas_rag
        texto_base       = limpiar_marcas_rag(state.get("texto_iterado") or state["contexto_recuperado"])

        historial_textos = list(state.get("historial_textos") or [])
        if not historial_textos:
            historial_textos.append(state.get("contexto_recuperado") or "")

        puntaje_estimado = float(state.get("puntaje_estimado") or 0.0)
        puntaje_max      = float(state.get("_puntaje_max") or 0.0)
        porcentaje       = (puntaje_estimado / puntaje_max) if puntaje_max > 0 else 0.0
        # En modo NÚCLEO siempre se ESCRIBE (su "puntaje" contra criterios genéricos no
        # es una nota real; entrar en pulido devolvería el contexto sin mejorar y se
        # saltaría el plan peso+margen).
        supera_umbral    = (porcentaje > _UMBRAL_EXCELENCIA) and not modo_nucleo

        universidad_l = str(universidad).lower()
        # El núcleo NO es la sección "título" aunque su nombre contenga la palabra.
        es_titulo = _es_seccion_titulo(seccion) and not modo_nucleo
        es_upao   = "upao" in universidad_l or "antenor orrego" in universidad_l

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
                    "Aplica los retoques mínimos y devuelve `texto_redactado` (texto pulido) "
                    "y `recomendaciones` (qué retocaste)."
                )),
            ])
            chain_pul = prompt_pul | llm.with_structured_output(RedaccionSeccion)

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
                texto_final      = (output.texto_redactado or "").strip() or texto_base
                sugerencias_texto = (output.recomendaciones or "").strip() or (
                    f"Tu texto ya está en nivel ({porcentaje:.0%}); no hizo falta ningún retoque."
                )
            except Exception as exc:
                logger.warning(f"[Redactor/Pulidor] Falló: {exc} — usando fallback")
                texto_final = texto_base
                sugerencias_texto = (
                    f"Sección aprobada con excelente puntuación ({porcentaje:.0%}). "
                    f"No hay retoques de pulido adicionales."
                )

            # Aun en pulido, el título UPAO no puede exceder 20 palabras.
            if es_titulo and es_upao:
                n_pal = _palabras_titulo(texto_final)
                if n_pal > 20:
                    sugerencias_texto += (
                        f"\n\n**Atención:** el título tiene {n_pal} palabras; UPAO exige máximo 20 "
                        "(incluyendo conectores y fechas). Recórtalo conservando variables y unidad de análisis."
                    )

            notas_na = _notas_na_tipo(state)
            if notas_na:
                sugerencias_texto += "\n\n" + notas_na

            historial_textos.append(texto_final)

            return {
                "texto_iterado":                 texto_final,
                "numero_iteracion":              iteracion_actual,
                "loras_activas":                 ["redactor_pulidor"],
                "redactor_sugerencias_mejoras":  sugerencias_texto,
                "redactor_evaluacion_rubrica":   None,
                "redactor_solo_pulido":          True,
                "historial_textos":              historial_textos,
            }

        
        evaluacion_rubrica_dict = None


        logger.info("[Redactor] Subagente 1 ejecutando reescritura del texto...")
        
        from ._rubrica import criterios_para_seccion
        crit = criterios_para_seccion(state, seccion)
        criterios_str = crit["criterios_str"]

        from backend.enfoque import bloque_enfoque
        enfoque = bloque_enfoque(state.get("tipo_investigacion"), state.get("diseno"))

        # Paquete de coherencia: reusa el contexto que ya planificó el auditor en
        # esta iteración (mismo proyecto/sección) en vez de gastar otra llamada RAG.
        contexto_dinamico = state.get("contexto_coherencia") or obtener_contexto_dinamico(
            llm              = llm,
            seccion          = seccion,
            texto_snippet    = texto_base[:500],
            rol              = "redactor académico que mejora secciones de tesis de ingeniería",
            criterios        = criterios_str,
            feedback_auditor = state.get("feedback_auditor") or state.get("observaciones_metodologicas") or "",
        )

        # Brecha hacia la meta: aunque no queden "errores", si el puntaje sigue por
        # debajo del objetivo el redactor debe empujar los ítems al máximo.
        import math
        meta            = float(state.get("meta_aprobacion") or 0.90)
        meta_pts        = math.ceil(puntaje_max * meta) if puntaje_max else 0
        items_mejorables = state.get("items_mejorables") or []
        if items_mejorables:
            brecha_items = "\n".join(
                f"- Ítem {it.get('item_numero', '?')}: actualmente en {it.get('puntaje', '?')} "
                f"(debe llegar al máximo) — {it.get('observacion', '')}"
                for it in items_mejorables
            )
        else:
            brecha_items = "Sin ítems puntuales pendientes; eleva la calidad y completitud general."
        brecha_meta = (
            f"Puntaje actual: {int(puntaje_estimado)}/{int(puntaje_max)}; meta: {meta_pts}/{int(puntaje_max)} "
            f"({meta:.0%}). Ítems aún por debajo del máximo:\n{brecha_items}\n"
            "Cierra EXACTAMENTE esa brecha en esta versión; no te quedes en el mismo nivel de la iteración anterior."
        )

        # Modo NÚCLEO: el redactor trabaja el esqueleto de coherencia en una sola pasada.
        # Solo REESCRIBE (texto mejorado) los subpuntos prioritarios (peso en la rúbrica +
        # margen de mejora); para el RESTO entrega solo una OBSERVACIÓN del porqué de su nota.
        if state.get("modo_nucleo"):
            instruccion_nucleo = _instruccion_nucleo(state.get("nucleo_plan"))
        else:
            instruccion_nucleo = "—"

        # Regla institucional del título (p. ej. UPAO ≤ 20 palabras).
        if es_titulo and es_upao:
            regla_titulo = (
                "REGLA INSTITUCIONAL UPAO PARA EL TÍTULO: el título DEBE tener MÁXIMO 20 PALABRAS "
                "(contando conectores, artículos, preposiciones, fechas y siglas). Cuéntalas y, si excede, "
                "reescríbelo más conciso SIN perder las variables, la unidad de análisis ni el enfoque. "
                "Apóyate en la problemática, los objetivos, las variables y el diseño para que el título sea correcto."
            )
        elif es_titulo:
            regla_titulo = (
                "Para el TÍTULO, apóyate en la problemática, los objetivos, las variables y el diseño para "
                "verificar que sea claro, específico y coherente con el estudio."
            )
        else:
            regla_titulo = ""

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
            "perfil_institucional":     state.get("perfil_institucional") or "Sin lineamientos institucionales adicionales.",
            "enfoque":                  enfoque,
            "brecha_meta":              brecha_meta,
            "regla_titulo":             regla_titulo or "—",
            "instruccion_nucleo":       instruccion_nucleo,
            "contexto_secciones_relacionadas": "",
        }

        prompt_esc = ChatPromptTemplate.from_messages([
            ("system", _PROMPT_ESCRITOR),
            ("human", (
                "{enfoque}\n\n"
                "Genera la versión mejorada del texto para la sección **{seccion}** (iteración #{iteracion}).\n\n"
                "**TEXTO ORIGINAL:**\n{texto_actual}\n\n"
                "**ERRORES CONFIRMADOS POR EL PANEL:**\n{errores_confirmados}\n\n"
                "**BRECHA HACIA LA META (cierra esto):**\n{brecha_meta}\n\n"
                "**MODO NÚCLEO:**\n{instruccion_nucleo}\n\n"
                "**REGLA DEL TÍTULO:**\n{regla_titulo}\n\n"
                "**FEEDBACK METODOLÓGICO:**\n{observaciones_metodologicas}\n\n"
                "**CONTEXTO RAG DE LIBROS:**\n{contexto_teorico}\n\n"
                "**CONTEXTO DE OTRAS SECCIONES:**\n{contexto_dependencias}\n\n"
                "**LINEAMIENTOS DE LA UNIVERSIDAD (ajusta el estilo y exigencias a esto):**\n{perfil_institucional}\n\n"
                "Devuelve `texto_redactado` (solo la sección, limpia) y `recomendaciones` "
                "(lo que no cuadra con el enfoque o no debe forzarse en el texto)."
            )),
        ])
        chain_esc = prompt_esc | llm.with_structured_output(RedaccionSeccion)

        sugerencias_escritor = None
        try:
            output_esc = invocar_con_backoff(chain_esc, inputs_base)
            texto_final = (output_esc.texto_redactado or "").strip() or texto_base
            sugerencias_escritor = (output_esc.recomendaciones or "").strip() or None
        except Exception as exc:
            logger.warning(f"[Redactor/Escritor] Falló: {exc} — usando fallback")
            texto_final = texto_base

        # Red de seguridad determinista: título UPAO ≤ 20 palabras.
        if es_titulo and es_upao and texto_final:
            n_pal = _palabras_titulo(texto_final)
            if n_pal > 20:
                aviso = (
                    f"**Atención:** el título propuesto tiene {n_pal} palabras; UPAO exige "
                    "máximo 20 (incluyendo conectores y fechas). Recórtalo conservando las "
                    "variables y la unidad de análisis."
                )
                sugerencias_escritor = (
                    f"{sugerencias_escritor}\n\n{aviso}" if sugerencias_escritor else aviso
                )
                logger.info(f"[Redactor] Título UPAO con {n_pal} palabras (>20) — aviso añadido")

        notas_na = _notas_na_tipo(state)
        if notas_na:
            sugerencias_escritor = (
                f"{sugerencias_escritor}\n\n{notas_na}" if sugerencias_escritor else notas_na
            )

        historial_textos.append(texto_final)

        return {
            "texto_iterado":                 texto_final,
            "numero_iteracion":              iteracion_actual,
            "loras_activas":                 ["redactor_escritor", "redactor_evaluador"],
            "redactor_sugerencias_mejoras":  sugerencias_escritor,
            "redactor_evaluacion_rubrica":   evaluacion_rubrica_dict,
            "redactor_solo_pulido":          False,
            "historial_textos":              historial_textos,
        }

    return nodo_redactor

def _es_seccion_titulo(seccion: str) -> bool:
    s = (seccion or "").lower()
    return "título" in s or "titulo" in s or "title" in s


def _palabras_titulo(texto: str) -> int:
    """Cuenta palabras del título, quitando una etiqueta inicial tipo «Título: …»."""
    import re
    t = (texto or "").strip()
    t = re.sub(r'(?i)^\s*t[íi]tulo[^\n:]*[:\n]', ' ', t, count=1)
    return len(re.findall(r"\S+", t))


def _instruccion_nucleo(plan: dict | None) -> str:
    """Instrucción del modo NÚCLEO según el plan (qué reescribir vs solo observar).

    `plan = {"reescribir": [secciones], "observar": [{"seccion","puntaje","maximo","razones"}]}`.
    Sin plan → comportamiento clásico: reescribir todos los subpuntos.
    """
    plan = plan or {}
    reescribir = plan.get("reescribir") or []
    observar   = plan.get("observar") or []

    if not reescribir and not observar:
        return (
            "Estás mejorando el NÚCLEO DE COHERENCIA del proyecto (varios subpuntos juntos). "
            "En `texto_redactado` entrega el texto mejorado de CADA subpunto, separado por "
            "encabezados markdown (### Título, ### Problema/Pregunta, ### Objetivos, "
            "### Hipótesis, ### Variables, y los que apliquen). Asegura la TRAZABILIDAD entre "
            "ellos y con el tipo/diseño, la población y el método; no fuerces lo que el tipo no requiere."
        )

    lin_re = "\n".join(f"- {s}" for s in reescribir) or "- (ninguno: ya están en nivel)"
    lin_obs = []
    for o in observar:
        rz = "; ".join(r for r in (o.get("razones") or []) if r) or "según la calificación de la rúbrica"
        pj, mx = o.get("puntaje"), o.get("maximo")
        nota = f" (nota {pj}/{mx})" if pj is not None and mx else ""
        lin_obs.append(f"- {o.get('seccion')}{nota}: {rz}")
    lin_obs_txt = "\n".join(lin_obs) or "- (ninguno)"

    return (
        "Estás trabajando el NÚCLEO DE COHERENCIA del proyecto. Tienes DOS tareas DISTINTAS y "
        "todo va dentro de `texto_redactado`, cada subpunto bajo su encabezado markdown `### <nombre>`:\n\n"
        "A) REESCRIBE (texto mejorado COMPLETO, listo para entregar) SOLO estos subpuntos prioritarios:\n"
        f"{lin_re}\n\n"
        "B) NO reescribas los demás. Para CADA uno de estos escribe ÚNICAMENTE una OBSERVACIÓN breve "
        "(1-2 frases) que EXPLIQUE por qué tiene su nota actual (qué cumple y qué le falta). "
        "NO redactes contenido de tesis para ellos; empieza la línea con «Observación:»:\n"
        f"{lin_obs_txt}\n\n"
        "En AMBOS casos respeta la TRAZABILIDAD entre subpuntos y con el tipo/diseño, la población y el "
        "método; no fuerces lo que el tipo no requiere. En `recomendaciones` resume las incongruencias "
        "globales de coherencia."
    )


def _notas_na_tipo(state: MentoriaState) -> str:
    """Mensaje DUAL para ítems que el tipo no exige pero la rúbrica sí califica:
    no son errores (por el tipo), pero el jurado los evalúa → tenerlos en cuenta."""
    na = state.get("items_na_tipo") or []
    if not na:
        return ""
    lineas = [
        "**Criterios que tu rúbrica exige pero tu tipo de investigación no requiere** "
        "(no son errores; el sistema no los penalizó, pero el jurado los califica con esta rúbrica):"
    ]
    for it in na:
        n   = it.get("item_numero", "?")
        obs = (it.get("observacion") or "").strip()
        lineas.append(
            f"- Ítem {n}: por tu tipo/diseño de investigación no es exigible (no penaliza). "
            f"Aun así tu rúbrica lo evalúa; considéralo o justifica su ausencia ante el jurado. {obs}"
        )
    return "\n".join(lineas)


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
