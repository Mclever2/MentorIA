"""Utilidades internas compartidas por los nodos del grafo."""

import os
import time
import random
import logging
import numpy as np

logger = logging.getLogger(__name__)

_PROMPTS_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(__file__)
        )
    ),
    "prompts",
)


def cargar_prompt(nombre_archivo: str) -> str:
    """Lee y devuelve el contenido de un archivo de prompt Markdown."""
    ruta = os.path.join(_PROMPTS_DIR, nombre_archivo)
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def invocar_con_backoff(chain, inputs: dict, max_reintentos: int = 3):
    """
    Llama al LLM con reintentos de backoff exponencial ante errores transitorios.
    Reintenta en: rate limit (429), connection errors y timeouts.
    Espera base: 5 s × 2^intento + jitter aleatorio (0-2 s).
    """
    for intento in range(max_reintentos):
        try:
            return chain.invoke(inputs)
        except Exception as exc:
            msg = str(exc).lower()
            es_transitorio = (
                "429" in msg
                or "rate_limit" in msg
                or "connection" in msg
                or "timeout" in msg
                or "connect" in msg
            )
            if es_transitorio and intento < max_reintentos - 1:
                espera = (2 ** intento) * 5 + random.uniform(0, 2)
                causa = getattr(exc, "__cause__", None)
                logger.warning(
                    f"Error transitorio (intento {intento + 1}/{max_reintentos}): "
                    f"{type(exc).__name__}: {exc} | "
                    f"Causa: {type(causa).__name__}: {causa}. Esperando {espera:.1f}s…"
                )
                time.sleep(espera)
            else:
                raise
    raise RuntimeError("Se agotaron los reintentos.")


def calcular_consenso_matematico(scores: list, umbral_std: float = 0.5) -> dict:
    """
    Determina consenso matemáticamente a partir de una lista de scores numéricos.
    NO usa LLM. std_dev <= umbral → consenso; caso contrario → debate necesario.
    """
    if not scores:
        return {"hay_consenso": False, "motivo": "sin scores"}

    arr = np.array(scores, dtype=float)
    media = float(np.mean(arr))
    std_dev = float(np.std(arr))
    moda_score = float(max(set(scores), key=scores.count))

    hay_consenso = std_dev <= umbral_std

    return {
        "hay_consenso": hay_consenso,
        "score_consenso": round(moda_score if hay_consenso else media, 3),
        "media": round(media, 3),
        "std_dev": round(std_dev, 3),
        "activar_debate": not hay_consenso,
        "motivo": (
            f"std_dev={std_dev:.2f} <= {umbral_std} → consenso"
            if hay_consenso
            else f"std_dev={std_dev:.2f} > {umbral_std} → debate necesario"
        ),
    }
