"""
Intérprete de intención del chat.

Una sola llamada barata a gpt-4o-mini decide qué hacer con el mensaje del
usuario: lanzar la revisión completa, revisar secciones específicas del TOC,
o responder conversacionalmente (sin lanzar el grafo → cero tokens de agentes).
"""

import logging

from langchain_core.messages import SystemMessage, HumanMessage

from .llm import llm_rapido, extraer_json

logger = logging.getLogger(__name__)

_PROMPT_SISTEMA = """Eres el enrutador de un sistema multiagente que revisa proyectos de tesis.
Tu ÚNICA tarea es clasificar el mensaje del estudiante. Responde SOLO con JSON válido:

{{
  "modo": "completo" | "secciones" | "conversacion",
  "secciones": ["nombre exacto de la lista"]
}}

Reglas:
- "completo": pide revisar/evaluar TODO el proyecto, la tesis entera, una revisión general o los puntos débiles globales.
- "secciones": pide revisar/evaluar/corregir partes concretas (objetivos, hipótesis, metodología, marco teórico,
  título, justificación, etc.). En "secciones" usa SOLO nombres EXACTOS de la lista del documento. Máximo 3.
  Considera el HISTORIAL: si antes hablaron de una sección y ahora dice «sí, revísala» o «corrígela», resuélvelo a esa sección.
- "conversacion": saludos, dudas metodológicas, preguntas sobre cómo funciona el sistema, preguntas sobre resultados
  previos, o CUALQUIER cosa que no sea una orden explícita de ejecutar una revisión. Ante la duda, usa "conversacion".

SECCIONES DEL DOCUMENTO:
{toc}

ÚLTIMOS TURNOS DE LA CONVERSACIÓN (para resolver referencias como «esa sección», «sí», «la anterior»):
{historial}
"""


def _historial_breve(historial: list[dict] | None) -> str:
    if not historial:
        return "(sin turnos previos)"
    lineas = []
    for t in historial[-6:]:
        rol = "Estudiante" if t.get("rol") == "user" else "MentorIA"
        contenido = (t.get("contenido") or "").strip().replace("\n", " ")
        if contenido:
            lineas.append(f"{rol}: {contenido[:200]}")
    return "\n".join(lineas) or "(sin turnos previos)"


def interpretar_mensaje(
    mensaje: str,
    toc_nombres: list[str],
    contexto_previo: str = "",
    hay_documento: bool = False,
    historial: list[dict] | None = None,
) -> dict:
    toc_txt = "\n".join(f"- {n}" for n in toc_nombres) if toc_nombres else "(sin documento cargado)"

    llm = llm_rapido(temperatura=0.0)
    try:
        respuesta = llm.invoke([
            SystemMessage(content=_PROMPT_SISTEMA.format(
                toc=toc_txt, historial=_historial_breve(historial),
            )),
            HumanMessage(content=mensaje),
        ])
        data = extraer_json(respuesta.content)
    except Exception as exc:
        logger.error(f"[intent] Error LLM: {exc}")
        data = {}

    modo = data.get("modo")
    if modo not in ("completo", "secciones", "conversacion"):
        msg = mensaje.lower()
        if any(p in msg for p in ("todo", "completo", "completa", "entera", "general")) and hay_documento:
            modo = "completo"
        else:
            modo = "conversacion"

    secciones = [s for s in (data.get("secciones") or []) if s in toc_nombres][:3]
    if modo == "secciones" and not secciones:
        modo = "completo" if hay_documento else "conversacion"

    # Sin documento no se puede revisar: el conversador se encarga de orientar/pedir el PDF.
    if modo != "conversacion" and not hay_documento:
        modo = "conversacion"

    return {"modo": modo, "secciones": secciones}
