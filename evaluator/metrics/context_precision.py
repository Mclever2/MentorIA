import logging
import os
import json
from concurrent.futures import ThreadPoolExecutor
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class RelevanciaChunk(BaseModel):
    es_relevante: bool = Field(description="True si el fragmento es relevante para el texto y la sección, False de lo contrario")
    explicacion: str = Field(description="Explicación breve de por qué es o no relevante")

_PROMPT_RELEVANCIA = """
Eres un evaluador experto de sistemas RAG (Generación Aumentada por Recuperación) para tesis académicas.
Tu tarea es determinar si el fragmento de libro recuperado (contexto RAG) contiene información relevante que sirvió de base o es pertinente para el texto final generado para la sección de tesis.

Sección de la Tesis:
{seccion}

Fragmento recuperado del Libro:
{chunk}

Texto Final Generado:
{texto_final}

Analiza si el fragmento de libro contiene conceptos metodológicos, teóricos o prácticos que se aplican o deberían aplicarse en el Texto Final Generado para esa Sección de la Tesis.
Responde de forma estructurada.
"""

def evaluar_relevancia_chunk(llm: ChatOpenAI, seccion: str, chunk: str, texto_final: str) -> bool:
    """Evalúa si un chunk individual es relevante."""
    if not chunk.strip():
        return False
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _PROMPT_RELEVANCIA),
        ])
        chain = prompt | llm.with_structured_output(RelevanciaChunk)
        res = chain.invoke({
            "seccion": seccion,
            "chunk": chunk,
            "texto_final": texto_final
        })
        return res.es_relevante
    except Exception as exc:
        logger.warning(f"Error evaluando relevancia de chunk: {exc}")
        return True

def calcular_context_precision(
    seccion: str,
    contexto_teorico: str,
    texto_final: str,
) -> dict:
    """
    Calcula el Context Precision sin referencia (Ragas style).
    Fórmula: mean(Precision@k * v_k) para k=1..K
    Donde v_k es 1 si el chunk k es relevante, 0 si no.
    Precision@k es la precisión acumulada hasta la posición k.
    """
    if not contexto_teorico.strip() or not texto_final.strip():
        return {
            "context_precision": 0.0,
            "chunks_totales": 0,
            "chunks_relevantes": 0,
            "interpretacion": "Sin contexto teórico o texto final"
        }

    chunks = [c.strip() for c in contexto_teorico.split("\n\n---\n\n") if c.strip()]
    if not chunks:
        return {
            "context_precision": 0.0,
            "chunks_totales": 0,
            "chunks_relevantes": 0,
            "interpretacion": "Sin chunks de contexto teórico"
        }

    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        llm = ChatOpenAI(
            api_key=api_key,
            model="gpt-4o-mini",
            temperature=0.0,
            max_retries=2
        )

        with ThreadPoolExecutor(max_workers=min(5, len(chunks))) as executor:
            futuros = [
                executor.submit(evaluar_relevancia_chunk, llm, seccion, chunk, texto_final)
                for chunk in chunks
            ]
            relevancias = [f.result() for f in futuros]

        k_relevantes = sum(1 for r in relevancias if r)
        if k_relevantes == 0:
            return {
                "context_precision": 0.0,
                "chunks_totales": len(chunks),
                "chunks_relevantes": 0,
                "interpretacion": "Ningún fragmento de libro recuperado es relevante para el texto"
            }

        suma_precision = 0.0
        relevantes_acumulados = 0
        for idx, es_rel in enumerate(relevancias, 1):
            if es_rel:
                relevantes_acumulados += 1
                precision_k = relevantes_acumulados / idx
                suma_precision += precision_k

        score = suma_precision / k_relevantes

        return {
            "context_precision": round(score, 4),
            "chunks_totales": len(chunks),
            "chunks_relevantes": k_relevantes,
            "interpretacion": (
                "alta relevancia RAG" if score > 0.8
                else "relevancia RAG moderada" if score > 0.5
                else "baja relevancia RAG (revisar recuperación)"
            )
        }
    except Exception as exc:
        logger.error(f"Error calculando Context Precision: {exc}")
        return {
            "context_precision": 0.0,
            "chunks_totales": len(chunks),
            "chunks_relevantes": 0,
            "interpretacion": f"Error en el cálculo: {exc}"
        }
