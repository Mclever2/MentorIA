"""
Enfoque / tipo de investigación — fuente única para que TODOS los agentes se
adapten al tipo declarado por el estudiante.

5 tipos soportados: cuantitativa, cualitativa, mixta, tecnologica, innovacion.

- `reglas_enfoque(tipo)`        → reglas que CUALQUIER agente debe respetar (no
                                  analizar una cualitativa como cuantitativa, etc.).
- `especialista_metodologico(tipo)` → modificador de rol para el subagente
                                  especialista del metodólogo (idea híbrida).
- `bloque_enfoque(tipo, diseno)` → bloque listo para inyectar en los prompts.

No depende de api/ ni del grafo: lo usan tanto los nodos como la capa API.
"""

from __future__ import annotations

from typing import Optional

TIPOS = ("cuantitativa", "cualitativa", "mixta", "tecnologica", "innovacion")

TIPO_DEFECTO = "cuantitativa"

# Etiqueta legible para UI/logs.
ETIQUETAS = {
    "cuantitativa": "Cuantitativa",
    "cualitativa":  "Cualitativa",
    "mixta":        "Mixta",
    "tecnologica":  "Tecnológica / Aplicada",
    "innovacion":   "Innovación / Desarrollo",
}


def normalizar_tipo(valor: Optional[str]) -> str:
    """Mapea texto libre del estudiante/LLM a uno de los 5 tipos canónicos."""
    t = (valor or "").strip().lower()
    if not t:
        return TIPO_DEFECTO
    import unicodedata
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    if "cuali" in t:
        return "cualitativa"
    if "mixt" in t or "mixed" in t:
        return "mixta"
    if "tecnolog" in t or "aplicad" in t or "ingenieri" in t or "desarrollo de software" in t:
        return "tecnologica"
    if "innovac" in t or "emprend" in t:
        return "innovacion"
    if "cuanti" in t:
        return "cuantitativa"
    return TIPO_DEFECTO


_REGLAS = {
    "cuantitativa": (
        "Enfoque CUANTITATIVO: se ESPERAN hipótesis contrastables, variables "
        "operacionalizadas (dimensiones/indicadores), muestreo y pruebas estadísticas. "
        "Trazabilidad: problema → objetivos → hipótesis → variables → método → análisis."
    ),
    "cualitativa": (
        "Enfoque CUALITATIVO: NO exijas hipótesis estadísticas ni operacionalización de "
        "variables. Se trabaja con CATEGORÍAS/subcategorías, supuestos, preguntas abiertas, "
        "muestreo intencional y criterios de rigor (credibilidad, transferibilidad, "
        "dependencia, confirmabilidad). Si el proyecto incluye hipótesis cuantitativas u "
        "operacionalización de variables, márcalo como INCONGRUENTE con el enfoque, no como acierto."
    ),
    "mixta": (
        "Enfoque MIXTO: coexisten una fase cuantitativa (hipótesis/variables) y una "
        "cualitativa (categorías). Evalúa además la INTEGRACIÓN: tipo de diseño mixto "
        "(secuencial explicativo/exploratorio o concurrente) y la coherencia entre ambas fases."
    ),
    "tecnologica": (
        "Enfoque TECNOLÓGICO/APLICADO (investigación de desarrollo o ingeniería): el centro es "
        "el ARTEFACTO/solución (requisitos, diseño, implementación, pruebas y validación). "
        "Puede NO haber hipótesis ni operacionalización clásicas; evalúa objetivos de desarrollo, "
        "la metodología de ingeniería (p. ej. Scrum, RUP, design science) y la validación del producto. "
        "No penalices la ausencia de hipótesis estadística si el tipo es tecnológico."
    ),
    "innovacion": (
        "Enfoque de INNOVACIÓN/DESARROLLO: foco en propuesta de valor, novedad, factibilidad "
        "(técnica/económica), prototipo y validación con usuarios o mercado. No exijas el marco "
        "cuantitativo clásico (hipótesis/variables); evalúa originalidad, viabilidad e impacto."
    ),
}


def reglas_enfoque(tipo: str) -> str:
    return _REGLAS.get(normalizar_tipo(tipo), _REGLAS[TIPO_DEFECTO])


def bloque_enfoque(tipo: Optional[str], diseno: Optional[str] = None) -> str:
    """Bloque para inyectar en cualquier prompt de agente."""
    t = normalizar_tipo(tipo)
    dis = (diseno or "").strip() or "no especificado"
    return (
        "## ENFOQUE DEL PROYECTO (tenlo SIEMPRE en cuenta)\n"
        f"- Tipo de investigación: **{ETIQUETAS[t]}**\n"
        f"- Diseño declarado: {dis}\n"
        f"- {reglas_enfoque(t)}\n"
        "COHERENCIA TIPO↔CONTENIDO: si el contenido NO corresponde al tipo/diseño declarado "
        "(p. ej. declara CUANTITATIVA pero mezcla hipótesis o categorías cualitativas → en realidad "
        "sería MIXTA; o usa una 2.ª variable/implícita cuando declaró una sola), NO lo des por bueno "
        "ni lo ignores: márcalo como incongruencia y recomienda DOS caminos — (a) alinear el "
        "tipo/diseño a lo que realmente hace, o (b) ajustar ese elemento para cumplir con el tipo "
        "declarado.\n"
        "RÚBRICA vs TIPO: si la rúbrica exige algo que tu tipo NO requiere, NO lo penalices por el "
        "tipo, pero AVISA con mensaje dual: «metodológicamente no es exigible para tu tipo, PERO tu "
        "rúbrica lo evalúa», y evalúa según SU proyecto concreto si conviene cubrirlo o justificar su "
        "ausencia ante el jurado, con una recomendación accionable.\n"
        "FUNDAMENTO (no alucines): basa tus juicios y refutaciones en los libros de metodología del "
        "CONTEXTO TEÓRICO cuando estén disponibles; si ahí no hay soporte, razona con criterio "
        "metodológico estándar pero NO inventes citas, autores ni datos.\n"
        "Adecúa tu análisis y tus recomendaciones a ESTE enfoque; no apliques criterios de otro tipo."
    )


_ESPECIALISTA = {
    "cuantitativa": (
        "Eres metodólogo especialista en investigación CUANTITATIVA (rutas de Hernández-Sampieri). "
        "Verifica el rigor cuantitativo: validez del diseño (experimental, cuasi, no experimental), "
        "operacionalización de variables, hipótesis falsables, muestreo y pruebas estadísticas "
        "coherentes con la escala de medición."
    ),
    "cualitativa": (
        "Eres metodólogo especialista en investigación CUALITATIVA (ruta cualitativa de "
        "Hernández-Sampieri). Verifica el rigor cualitativo: adecuación del diseño "
        "(fenomenológico, etnográfico, teoría fundamentada, estudio de caso, narrativo), coherencia "
        "categorías↔preguntas↔objetivos, muestreo intencional/teórico y criterios de rigor "
        "(credibilidad, transferibilidad, dependencia, confirmabilidad). NO apliques criterios cuantitativos."
    ),
    "mixta": (
        "Eres metodólogo especialista en investigación MIXTA. Verifica la coherencia de AMBAS fases "
        "(cuanti y cuali) y, sobre todo, la INTEGRACIÓN: el diseño mixto declarado (secuencial "
        "explicativo/exploratorio o concurrente), el punto de integración y la consistencia entre "
        "hipótesis/variables (fase cuanti) y categorías (fase cuali)."
    ),
    "tecnologica": (
        "Eres metodólogo especialista en investigación TECNOLÓGICA/APLICADA y de desarrollo. "
        "Verifica el rigor de ingeniería: definición de requisitos, metodología de desarrollo "
        "(Scrum, RUP, design science research…), arquitectura/diseño de la solución, y el plan de "
        "PRUEBAS/validación del artefacto. No exijas hipótesis ni operacionalización si el tipo no las requiere."
    ),
    "innovacion": (
        "Eres metodólogo especialista en proyectos de INNOVACIÓN/DESARROLLO. Verifica la solidez de "
        "la propuesta: problema/oportunidad, propuesta de valor y novedad, factibilidad técnica y "
        "económica, prototipo y plan de validación con usuarios o mercado. Evalúa con criterios de "
        "innovación, no con el marco cuantitativo clásico."
    ),
}


def especialista_metodologico(tipo: str) -> str:
    return _ESPECIALISTA.get(normalizar_tipo(tipo), _ESPECIALISTA[TIPO_DEFECTO])
