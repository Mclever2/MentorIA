"""LLM ligero para la capa de orquestación de la API (intent + barrido + síntesis)."""

import os
import json
import re
import logging

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def llm_rapido(temperatura: float = 0.0) -> ChatOpenAI:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("No se encontró 'OPENAI_API_KEY' en el entorno.")
    return ChatOpenAI(
        api_key=api_key,
        model="gpt-4o-mini",
        temperature=temperatura,
        max_retries=2,
        timeout=60.0,
    )


def extraer_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta LLM (tolera ```json fences)."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.MULTILINE).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning(f"[llm] No se pudo parsear JSON de: {texto[:200]}")
    return {}
