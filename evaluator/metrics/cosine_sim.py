import numpy as np
import logging
from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

def calcular_similitud_coseno(texto_inicial: str, texto_final: str) -> dict:
    if not texto_inicial.strip() or not texto_final.strip():
        return {"similitud_coseno": 0.0, "interpretacion": "texto vacío"}

    try:
        embed_fn = HuggingFaceEmbeddings(
            model_name="intfloat/multilingual-e5-small",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        
        emb_inicial = embed_fn.embed_query(f"query: {texto_inicial}")
        emb_final = embed_fn.embed_query(f"query: {texto_final}")
        
        similitud = float(np.dot(emb_inicial, emb_final))
        
        return {
            "similitud_coseno": round(similitud, 4),
            "interpretacion": (
                "alta similitud semántica (sin desviaciones)" if similitud > 0.90
                else "similitud moderada (preserva el sentido general)" if similitud > 0.75
                else "cambio semántico sustancial (posible desvío)" if similitud > 0.55
                else "desviación temática crítica / cambio de sentido total"
            ),
        }
    except Exception as exc:
        logger.warning(f"Error calculando similitud con multilingual-e5: {exc}. Usando fallback TF-IDF.")
        
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        
        try:
            vectorizer = TfidfVectorizer()
            tfidf_matrix = vectorizer.fit_transform([texto_inicial, texto_final])
            similitud = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return {
                "similitud_coseno": round(float(similitud), 4),
                "interpretacion": (
                    "alta similitud temática (TF-IDF)" if similitud > 0.70
                    else "coherencia temática media (TF-IDF)" if similitud > 0.40
                    else "posible desviación temática (TF-IDF)"
                ),
            }
        except Exception as fallback_exc:
            logger.error(f"Fallo crítico en fallback de similitud: {fallback_exc}")
            return {
                "similitud_coseno": 0.0,
                "interpretacion": f"Error en cálculo: {fallback_exc}"
            }
