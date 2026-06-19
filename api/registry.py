"""
Registros en memoria del proceso: documentos vectorizados y runs activos.

El vector store de cada tesis es un Chroma EphemeralClient (no serializable),
por eso vive aquí y no en una base de datos. Con Cloud Run min-instances=1
el registro sobrevive entre requests; si el proceso se reinicia, el frontend
pide re-subir el PDF (los metadatos del historial persisten en Supabase).
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

_MAX_DOCS = 20
_MAX_RUNS = 50


@dataclass
class DocumentoActivo:
    doc_id: str
    user_id: str
    nombre: str
    pdf_hash: str
    vector_store: Any
    estructura_toc: dict
    stats: list
    rubrica: Optional[dict] = None
    rubrica_nombre: Optional[str] = None
    universidad: Optional[str] = None
    programa: Optional[str] = None
    perfil_institucional: Optional[str] = None
    tipo_investigacion: Optional[str] = None
    diseno: Optional[str] = None
    creado_en: float = field(default_factory=time.time)
    evaluadas: set = field(default_factory=set)
    mejoras: dict = field(default_factory=dict)
    # Resumen compacto de la última revisión (completa o por secciones), para que el
    # agente de chat rápido no pierda el hilo. {"tipo","texto"}.
    ultima_revision: dict = field(default_factory=dict)


@dataclass
class RunActivo:
    run_id: str
    user_id: str
    doc_id: str
    modo: str
    secciones: list
    max_iteraciones: int
    estado: str = "pendiente"
    cancelar: threading.Event = field(default_factory=threading.Event)
    creado_en: float = field(default_factory=time.time)


_DOCS: dict[str, DocumentoActivo] = {}
_RUNS: dict[str, RunActivo] = {}
_reg_lock = threading.Lock()

RUN_EXCLUSIVO = threading.Lock()


def _evict(d: dict, max_items: int) -> None:
    while len(d) > max_items:
        mas_viejo = min(d.values(), key=lambda x: x.creado_en)
        d.pop(mas_viejo.doc_id if isinstance(mas_viejo, DocumentoActivo) else mas_viejo.run_id, None)


def registrar_documento(**kwargs) -> DocumentoActivo:
    with _reg_lock:
        doc = DocumentoActivo(doc_id=str(uuid.uuid4()), **kwargs)
        _DOCS[doc.doc_id] = doc
        _evict(_DOCS, _MAX_DOCS)
        return doc


def obtener_documento(doc_id: str) -> Optional[DocumentoActivo]:
    return _DOCS.get(doc_id)


def buscar_documento_por_hash(user_id: str, pdf_hash: str) -> Optional[DocumentoActivo]:
    for doc in _DOCS.values():
        if doc.user_id == user_id and doc.pdf_hash == pdf_hash:
            return doc
    return None


def registrar_run(**kwargs) -> RunActivo:
    with _reg_lock:
        run = RunActivo(run_id=str(uuid.uuid4()), **kwargs)
        _RUNS[run.run_id] = run
        _evict(_RUNS, _MAX_RUNS)
        return run


def obtener_run(run_id: str) -> Optional[RunActivo]:
    return _RUNS.get(run_id)
