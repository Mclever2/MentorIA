"""
Detección automática del tipo de investigación desde el RAG del proyecto.

Lee del vector store lo que el estudiante DECLARÓ en "Tipo de investigación" /
"Diseño" / "Método" y un LLM barato lo clasifica en uno de los 5 tipos
canónicos (backend.enfoque.TIPOS) + extrae el diseño declarado.

Se cachea en el DocumentoActivo (1 vez por proyecto) para no repetir la llamada.
"""

import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.enfoque import normalizar_tipo, TIPO_DEFECTO
from .llm import llm_rapido, extraer_json

logger = logging.getLogger(__name__)

_QUERIES = [
    "tipo de investigación enfoque cuantitativo cualitativo mixto tecnológico aplicado",
    "diseño del estudio método de investigación nivel alcance",
]

_PROMPT = """Eres un metodólogo. A partir del texto de un proyecto de tesis (secciones de tipo, \
método y diseño), determina el ENFOQUE/tipo de investigación declarado y su diseño.

Responde SOLO JSON válido:
{{
  "tipo": "cuantitativa" | "cualitativa" | "mixta" | "tecnologica" | "innovacion",
  "diseno": "diseño declarado en pocas palabras (p. ej. 'no experimental, transversal, correlacional')",
  "evidencia": "frase breve del texto que lo sustenta"
}}

Guía:
- "cuantitativa": mide variables, hipótesis, estadística.
- "cualitativa": categorías, fenomenológico/etnográfico/estudio de caso, sin hipótesis estadística.
- "mixta": combina cuantitativa y cualitativa.
- "tecnologica": investigación aplicada/de desarrollo centrada en construir un artefacto o solución de ingeniería.
- "innovacion": proyecto de innovación/emprendimiento centrado en propuesta de valor y prototipo.
Si no hay evidencia clara, elige el más probable según el contenido.

TEXTO DEL PROYECTO (tipo/método/diseño):
{texto}
"""


def detectar_tipo_y_diseno(doc) -> tuple[str, str]:
    """Clasifica el tipo y extrae el diseño desde el RAG. Fallback: cuantitativa."""
    vs = getattr(doc, "vector_store", None)
    if vs is None:
        return TIPO_DEFECTO, ""

    partes: list[str] = []
    try:
        for q in _QUERIES:
            for d in vs.similarity_search(q, k=3):
                if d.page_content not in partes:
                    partes.append(d.page_content)
    except Exception as exc:
        logger.warning(f"[tipo] RAG falló: {exc}")

    texto = "\n\n".join(partes)[:6000]
    if not texto.strip():
        return TIPO_DEFECTO, ""

    try:
        resp = llm_rapido(temperatura=0.0).invoke([
            SystemMessage(content=_PROMPT.format(texto=texto)),
            HumanMessage(content="Clasifica el tipo de investigación."),
        ])
        data = extraer_json(resp.content)
    except Exception as exc:
        logger.warning(f"[tipo] Clasificación LLM falló: {exc}")
        data = {}

    tipo = normalizar_tipo((data or {}).get("tipo"))
    diseno = ((data or {}).get("diseno") or "").strip()
    logger.info(f"[tipo] Detectado: {tipo} | diseño: {diseno or '—'}")
    return tipo, diseno


def obtener_tipo_diseno(doc) -> tuple[str, str]:
    """Devuelve (tipo, diseno) cacheado en el doc; lo detecta la primera vez."""
    if getattr(doc, "tipo_investigacion", None):
        return doc.tipo_investigacion, getattr(doc, "diseno", "") or ""
    tipo, diseno = detectar_tipo_y_diseno(doc)
    doc.tipo_investigacion = tipo
    doc.diseno = diseno
    return tipo, diseno
