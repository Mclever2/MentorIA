"""
Memoria del hilo de asesoría: texto corregido por sección.

Cuando el estudiante acepta «incorporar» una mejora, el texto corregido
reemplaza los fragmentos de ESA sección dentro del vector store de la tesis
(Chroma en memoria). El PDF original nunca se modifica — solo cambia lo que
los agentes recuperan vía RAG en las siguientes revisiones.
"""

import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 600
_CHUNK_OVERLAP = 80


def registrar_resultado(doc, seccion: str, resumen: dict) -> None:
    """Marca la sección como evaluada y guarda su texto corregido (si lo hay)."""
    doc.evaluadas.add(seccion)
    texto = (resumen.get("texto_mejorado") or "").strip()
    if texto:
        doc.mejoras[seccion] = {"texto": texto, "aplicada": False}


def pendientes(doc) -> list[str]:
    return [s for s, m in doc.mejoras.items() if not m.get("aplicada")]


def exportar_memoria(doc) -> dict:
    """Serializa la memoria del hilo para persistirla en la base de datos."""
    return {
        "evaluadas": sorted(doc.evaluadas),
        "aplicadas": {s: m["texto"] for s, m in doc.mejoras.items() if m.get("aplicada")},
        "pendientes": {s: m["texto"] for s, m in doc.mejoras.items() if not m.get("aplicada")},
        "ultima_revision": doc.ultima_revision or {},
    }


def restaurar_memoria(doc, memoria: dict) -> None:
    """
    Reconstruye la memoria del hilo tras re-indexar el PDF (rehidratación).
    Reaplica al vector store el texto corregido que ya estaba incorporado y
    re-registra como pendiente el que aún no lo estaba.
    """
    if not memoria:
        return

    if memoria.get("ultima_revision"):
        doc.ultima_revision = memoria["ultima_revision"]

    for s in memoria.get("evaluadas", []):
        doc.evaluadas.add(s)

    for seccion, texto in (memoria.get("aplicadas") or {}).items():
        doc.evaluadas.add(seccion)
        doc.mejoras[seccion] = {"texto": texto, "aplicada": False}
        try:
            _reemplazar_seccion(doc, seccion, texto)
            doc.mejoras[seccion]["aplicada"] = True
        except Exception as exc:
            logger.error(f"[mejoras] No se pudo restaurar '{seccion}': {exc}")

    for seccion, texto in (memoria.get("pendientes") or {}).items():
        doc.evaluadas.add(seccion)
        doc.mejoras.setdefault(seccion, {"texto": texto, "aplicada": False})

    logger.info(
        f"[mejoras] Memoria restaurada: {len(doc.evaluadas)} evaluadas, "
        f"{len(memoria.get('aplicadas') or {})} aplicadas reindexadas"
    )


def aplicar_pendientes(doc) -> list[str]:
    """Aplica todas las mejoras pendientes al vector store. Devuelve las aplicadas."""
    aplicadas: list[str] = []
    for seccion in pendientes(doc):
        try:
            _reemplazar_seccion(doc, seccion, doc.mejoras[seccion]["texto"])
            doc.mejoras[seccion]["aplicada"] = True
            aplicadas.append(seccion)
        except Exception as exc:
            logger.error(f"[mejoras] No se pudo aplicar '{seccion}': {exc}")
    return aplicadas


def _reemplazar_seccion(doc, seccion: str, texto: str) -> None:
    """Borra los fragmentos originales de la sección y reindexa el texto corregido."""
    col = doc.vector_store._collection

    res = col.get(where={"seccion": seccion}, include=["metadatas"])
    ids = res.get("ids") or []
    metas = res.get("metadatas") or []

    pagina = metas[0].get("pagina_inicio", 0) if metas else 0
    source = metas[0].get("source", "tesis") if metas else "tesis"
    base_idx = min((m.get("chunk_index", 0) for m in metas), default=0)

    if ids:
        col.delete(ids=ids)

    metadata = {
        "source":        source,
        "tipo":          "proyecto_tesis",
        "seccion":       seccion,
        "pagina_inicio": pagina,
        "mejorado":      True,
    }

    if len(texto) <= _CHUNK_SIZE:
        docs = [Document(page_content=texto, metadata=dict(metadata))]
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", "   ", " ", ""],
        )
        docs = splitter.create_documents([texto], metadatas=[metadata])

    for i, d in enumerate(docs):
        d.metadata["chunk_index"] = base_idx + i

    doc.vector_store.add_documents(docs)

    for s in doc.stats:
        if s.get("seccion") == seccion:
            s["chars"] = len(texto)
            s["n_fragmentos"] = len(docs)
            s["mejorado"] = True
            break

    logger.info(
        f"[mejoras] Sección '{seccion}' actualizada en memoria RAG: "
        f"{len(ids)} fragmentos originales → {len(docs)} corregidos"
    )
