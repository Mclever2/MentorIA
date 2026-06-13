"""
Singletons del proceso para la API.

Equivalente a frontend/resources.py pero sin Streamlit: el modelo de
embeddings, el grafo compilado y la biblioteca se cargan UNA vez por proceso.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_embeddings = None
_graph = None
_biblioteca = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        with _lock:
            if _embeddings is None:
                from backend.rag import cargar_modelo_embeddings
                logger.info("[deps] Cargando modelo de embeddings…")
                _embeddings = cargar_modelo_embeddings()
    return _embeddings


def get_graph():
    global _graph
    if _graph is None:
        with _lock:
            if _graph is None:
                from backend.graph.workflow import create_graph
                logger.info("[deps] Compilando grafo multiagente…")
                _graph = create_graph()
    return _graph


def get_biblioteca():
    global _biblioteca
    if _biblioteca is None:
        with _lock:
            if _biblioteca is None:
                from backend.rag import (
                    cargar_o_crear_biblioteca,
                    listar_libros,
                    precargar_libros_desde_carpeta,
                )
                logger.info("[deps] Cargando biblioteca metodológica…")
                vs = cargar_o_crear_biblioteca(get_embeddings())
                existentes = [l["nombre"] for l in listar_libros(vs)]
                nuevos = precargar_libros_desde_carpeta(vs, existentes)
                if nuevos:
                    logger.info(f"[deps] Pre-cargados {len(nuevos)} libro(s): {nuevos}")
                _biblioteca = vs
    return _biblioteca


def precalentar() -> None:
    """Carga todos los singletons al arrancar el proceso (evita latencia en la 1ª request)."""
    get_embeddings()
    get_graph()
    get_biblioteca()
