
import logging

from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

MODELO_EMBEDDING = "intfloat/multilingual-e5-small"


class MultilingualE5Embeddings(HuggingFaceEmbeddings):
    """
    Wrapper sobre HuggingFaceEmbeddings que añade los prefijos requeridos
    por el modelo multilingual-e5-small para RAG óptimo.

    - embed_query:     añade "query: "   (para búsquedas en ChromaDB)
    - embed_documents: añade "passage: " (para indexar fragmentos de texto)
    """

    def embed_documents(self, texts: list) -> list:
        prefixed = [f"passage: {t}" for t in texts]
        return super().embed_documents(prefixed)

    def embed_query(self, text: str) -> list:
        return super().embed_query(f"query: {text}")


def cargar_modelo_embeddings() -> MultilingualE5Embeddings:
    """
    Carga el modelo multilingual-e5-small en CPU.

    Primera ejecución: descarga ~117 MB (una sola vez, queda en caché local).
    Ejecuciones siguientes: carga desde ~/.cache/huggingface/hub/ (instantáneo).

    NOTA: Llamar con @st.cache_resource en Streamlit para mantener en memoria.

    IMPORTANTE: Si tenías libros indexados con all-MiniLM-L6-v2, debes
    re-subirlos desde el sidebar — la colección de biblioteca se renovó
    para usar el espacio vectorial del nuevo modelo.
    """
    logger.info(f"Cargando modelo de embeddings: {MODELO_EMBEDDING}")
    return MultilingualE5Embeddings(
        model_name=MODELO_EMBEDDING,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
