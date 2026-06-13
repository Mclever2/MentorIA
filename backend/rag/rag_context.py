"""
Contexto RAG activo para la sesión en curso.

Singleton de módulo — se establece desde pantalla_seleccion.py antes de
invocar el grafo y lo usan los nodos de los agentes en tiempo de ejecución.

Por qué un singleton y no el estado del grafo:
  El vector store (Chroma EphemeralClient) no es serializable por MemorySaver,
  así que no puede vivir en MentoriaState. El singleton es seguro en Streamlit
  porque cada sesión de usuario corre en un solo hilo.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_chroma import Chroma

logger = logging.getLogger(__name__)

_vector_store: Optional["Chroma"] = None


def set_vector_store(vs: "Chroma") -> None:
    """Registra el vector store de la sesión actual antes de invocar el grafo."""
    global _vector_store
    _vector_store = vs
    logger.info("[rag_context] Vector store registrado para la sesión actual")


def get_vector_store() -> Optional["Chroma"]:
    return _vector_store


_MAX_SECCIONES_BUSQUEDA = 3
_MAX_CHUNKS_POR_SECCION = 12


def buscar_fragmentos(query: str, k: int = 4, max_secciones: int = _MAX_SECCIONES_BUSQUEDA) -> str:
    """
    Búsqueda semántica libre en el vector store activo.

    Devuelve los fragmentos de las `max_secciones` secciones DISTINTAS más
    relevantes para la query — cada una con TODOS sus chunks en orden de lectura
    (chunk_index). A diferencia de la versión previa, NO colapsa el resultado a
    una única "sección dominante": así una query como 'objetivos específicos'
    puede traer una sección hermana aunque no sea la de mayor frecuencia, y un
    tema repartido en sub-secciones (metodología en 4.1/4.2/4.3…) no queda
    representado por una sola rebanada.

    Cada bloque se etiqueta '[i — sección]' para que el planner pueda filtrar por
    sección. Retorna "" si no hay vector store activo o no hay resultados.
    """
    if _vector_store is None:
        logger.debug("[rag_context] Sin vector store activo — búsqueda omitida")
        return ""
    try:
        n_total = _vector_store._collection.count()
        if n_total == 0:
            return ""

        todos_docs = _vector_store.similarity_search(query, k=n_total)
        if not todos_docs:
            return ""

        # Secciones distintas en orden de relevancia (primer hit de cada una).
        secciones_rank: list[str] = []
        for d in todos_docs:
            sec = d.metadata.get("seccion")
            if sec and sec not in secciones_rank:
                secciones_rank.append(sec)
            if len(secciones_rank) >= max_secciones:
                break

        if not secciones_rank:
            docs = todos_docs[:k]
            docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
            return "\n\n".join(f"[{i}]\n{d.page_content}" for i, d in enumerate(docs, 1))

        partes: list[str] = []
        idx = 1
        for sec in secciones_rank:
            chunks = [d for d in todos_docs if d.metadata.get("seccion") == sec]
            chunks.sort(key=lambda d: d.metadata.get("chunk_index", 0))
            for d in chunks[:_MAX_CHUNKS_POR_SECCION]:
                partes.append(f"[{idx} — {sec}]\n{d.page_content}")
                idx += 1
        return "\n\n".join(partes)
    except Exception as exc:
        logger.warning(f"[rag_context] Error en búsqueda: {exc}")
        return ""
