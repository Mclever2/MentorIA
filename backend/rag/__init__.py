"""
Paquete RAG — re-exporta todos los símbolos públicos.

Permite importar desde backend.rag directamente sin conocer la estructura interna:
    from backend.rag import extraer_texto_pdf, construir_vector_store, ...
"""

from .extractor      import extraer_texto_pdf, extraer_contenido_sin_indice
from .embeddings     import cargar_modelo_embeddings, MODELO_EMBEDDING
from .rubric_parser  import parse_rubrica_pdf, rubrica_a_texto_prompt
from .tesis_store   import (
    construir_vector_store,
    recuperar_contexto,
    recuperar_contexto_cruzado,
    recuperar_vista_general,
    obtener_stats_secciones,
)
from .library_store import (
    cargar_o_crear_biblioteca,
    agregar_libro,
    listar_libros,
    eliminar_libro,
    precargar_libros_desde_carpeta,
    recuperar_contexto_teorico,
)

__all__ = [
    "extraer_texto_pdf",
    "extraer_contenido_sin_indice",
    "cargar_modelo_embeddings",
    "MODELO_EMBEDDING",
    "parse_rubrica_pdf",
    "rubrica_a_texto_prompt",
    "construir_vector_store",
    "recuperar_contexto",
    "recuperar_contexto_cruzado",
    "recuperar_vista_general",
    "obtener_stats_secciones",
    "cargar_o_crear_biblioteca",
    "agregar_libro",
    "listar_libros",
    "eliminar_libro",
    "precargar_libros_desde_carpeta",
    "recuperar_contexto_teorico",
]
