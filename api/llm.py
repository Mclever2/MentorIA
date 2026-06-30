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


def _sanear_numeros_json(texto: str) -> str:
    """Quita ceros a la izquierda de enteros en posición de valor JSON.

    Los LLMs suelen devolver `"numero": 01` (porque los ítems se listan como
    «01.», «02.»), pero JSON NO admite ceros a la izquierda → json.loads revienta.
    Esto convierte `: 01` → `: 1`, `[01, 02]` → `[1, 2]`, sin tocar `0`, `0.5` ni
    enteros normales (10, 100). Solo actúa tras `:`, `,` o `[` (posición de valor),
    para no alterar el contenido de las cadenas de texto.
    """
    return re.sub(r"([:\[,]\s*)0+(\d)", r"\1\2", texto)


def extraer_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta LLM (tolera ```json fences y
    ceros a la izquierda en los números, p. ej. "numero": 01)."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.MULTILINE).strip()

    candidatos = [texto]
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if m:
        candidatos.append(m.group(0))

    for cand in candidatos:
        # 1er intento: tal cual. 2º intento: saneando ceros a la izquierda.
        for variante in (cand, _sanear_numeros_json(cand)):
            try:
                return json.loads(variante)
            except json.JSONDecodeError:
                continue

    logger.warning(f"[llm] No se pudo parsear JSON de: {texto[:200]}")
    return {}
