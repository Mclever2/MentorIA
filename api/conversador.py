"""
Agente conversacional (mentor metodológico).

Responde dudas del estudiante en el chat SIN lanzar la red de agentes:
  1. Fundamenta lo metodológico en los 4 libros indexados (RAG, fuente primaria).
  2. Si la pregunta es sobre su proyecto, consulta fragmentos de su propia tesis.
  3. Sigue el hilo de la conversación (recibe el historial del chat).

Usa gpt-4o-mini (barato) — no consume el presupuesto de la red multiagente.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .llm import llm_rapido

logger = logging.getLogger(__name__)

_K_LIBROS = 5
_K_TESIS = 4
_MAX_CHARS_FRAG = 700
_MAX_TURNOS_HISTORIAL = 12

_PROMPT_SISTEMA = """Eres MentorIA, un mentor metodológico experto que acompaña a un estudiante \
en su proyecto de tesis universitario. Conversas con él en un chat.

REGLAS (síguelas siempre):
1. Fundamenta tus respuestas a dudas metodológicas en los FRAGMENTOS DE LIBROS de abajo \
(son tu memoria: 4 libros de metodología de la investigación). Cuando uses una idea de un \
libro, menciónalo de forma natural (p. ej. «según {fuente_ejemplo}…»). No inventes teorías, \
autores ni citas que no estén en esos fragmentos; si los fragmentos no alcanzan, dilo con honestidad.
2. Si la pregunta es sobre el proyecto del estudiante, apóyate en los FRAGMENTOS DE SU TESIS y \
en las secciones que ya revisaste con él.
3. SIGUE EL HILO de la conversación. El estudiante YA subió su proyecto (su estructura está abajo) \
y quizá ya revisaste algunas secciones. Nunca le pidas volver a subir el PDF ni respondas como si \
no supieras nada de su proyecto.
4. Si te pide revisar, evaluar o corregir una sección (o todo el proyecto), NO lo hagas aquí: \
explícale brevemente que para eso la red de agentes hará la revisión y que te lo pida directamente \
(p. ej. «revisa mis objetivos»). Tú solo resuelves dudas y orientas.
5. Responde en español, claro y conciso, en markdown. Sé cálido pero directo.

ESTADO DEL PROYECTO DEL ESTUDIANTE:
{estado}

FRAGMENTOS DE LIBROS (tu memoria metodológica):
{libros}

FRAGMENTOS DE LA TESIS DEL ESTUDIANTE (su proyecto indexado):
{tesis}
"""


def _recuperar_libros(biblioteca, consulta: str) -> tuple[str, str]:
    """Devuelve (texto_contexto, una_fuente_de_ejemplo) desde los 4 libros."""
    try:
        if biblioteca is None or biblioteca._collection.count() == 0:
            return "", "los libros"
        docs = biblioteca.similarity_search(f"metodología de la investigación {consulta}", k=_K_LIBROS)
    except Exception as exc:
        logger.warning(f"[conversador] Error RAG libros: {exc}")
        return "", "los libros"

    if not docs:
        return "", "los libros"

    partes, fuente_ej = [], "los libros"
    for d in docs:
        fuente = d.metadata.get("fuente", "Fuente")
        fuente_ej = fuente
        partes.append(f"[{fuente}]\n{d.page_content[:_MAX_CHARS_FRAG]}")
    return "\n\n---\n\n".join(partes), fuente_ej


def _recuperar_tesis(doc, consulta: str) -> str:
    if doc is None:
        return ""

    vs = doc.vector_store
    fragmentos: list[tuple[str, str]] = []  # (seccion, texto)
    vistos: set[str] = set()

    # Siempre incluir la carátula/«Título del proyecto»: así el mentor conoce el
    # título y datos generales aunque la pregunta no se parezca a la portada.
    try:
        res = vs._collection.get(
            where={"seccion": "Título del proyecto"}, include=["documents"]
        )
        for t in (res.get("documents") or [])[:1]:
            if t and t not in vistos:
                fragmentos.append(("Título del proyecto", t))
                vistos.add(t)
    except Exception:
        pass

    # Fragmentos relevantes a la consulta.
    try:
        for d in vs.similarity_search(consulta, k=_K_TESIS):
            if d.page_content in vistos:
                continue
            fragmentos.append((d.metadata.get("seccion", ""), d.page_content))
            vistos.add(d.page_content)
    except Exception as exc:
        logger.warning(f"[conversador] Error RAG tesis: {exc}")

    if not fragmentos:
        return ""
    return "\n\n---\n\n".join(
        f"[{sec or 'fragmento'}]\n{texto[:_MAX_CHARS_FRAG]}" for sec, texto in fragmentos
    )


def _estado_proyecto(doc) -> str:
    if doc is None:
        return ("El estudiante AÚN NO ha subido su proyecto en este chat. "
                "Si su pregunta requiere su tesis, invítalo a subir el PDF con el botón de adjuntar (📎).")
    n_sec = len(doc.estructura_toc or {})
    revisadas = sorted(doc.evaluadas) if getattr(doc, "evaluadas", None) else []
    txt = f"- Documento: «{doc.nombre}» ({n_sec} secciones detectadas)."
    if revisadas:
        txt += "\n- Secciones que YA revisaste con la red de agentes en este chat: " + ", ".join(revisadas) + "."
    else:
        txt += "\n- Todavía no has corrido ninguna revisión formal en este chat."
    return txt


def _historial_a_mensajes(historial: list[dict]) -> list:
    msgs = []
    for turno in (historial or [])[-_MAX_TURNOS_HISTORIAL:]:
        rol = turno.get("rol")
        contenido = (turno.get("contenido") or "").strip()
        if not contenido:
            continue
        if rol == "user":
            msgs.append(HumanMessage(content=contenido[:2000]))
        elif rol == "assistant":
            msgs.append(AIMessage(content=contenido[:2000]))
    return msgs


def responder_consulta(
    mensaje: str,
    historial: list[dict],
    doc,
    biblioteca,
) -> str:
    """Genera la respuesta conversacional fundamentada en libros + tesis + hilo."""
    libros, fuente_ej = _recuperar_libros(biblioteca, mensaje)
    tesis = _recuperar_tesis(doc, mensaje)

    sistema = _PROMPT_SISTEMA.format(
        estado=_estado_proyecto(doc),
        libros=libros or "(sin fragmentos de libros recuperados para esta consulta)",
        tesis=tesis or "(sin fragmentos de la tesis — o el proyecto no está cargado)",
        fuente_ejemplo=fuente_ej,
    )

    mensajes = [SystemMessage(content=sistema)]
    mensajes.extend(_historial_a_mensajes(historial))
    mensajes.append(HumanMessage(content=mensaje))

    try:
        llm = llm_rapido(temperatura=0.3)
        return llm.invoke(mensajes).content.strip()
    except Exception as exc:
        logger.error(f"[conversador] Error LLM: {exc}")
        return ("Disculpa, tuve un problema procesando tu consulta. "
                "Intenta de nuevo en unos segundos.")
