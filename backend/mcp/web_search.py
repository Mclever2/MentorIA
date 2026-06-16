"""
Fuente MCP-estilo: búsqueda web de reglamentos/lineamientos de una universidad.

Usa Tavily (plan gratuito) para encontrar los reglamentos de grados/tesis de la
universidad que elija el estudiante. Se llama UNA vez al fijar la universidad
(no por run), así el costo es mínimo.

Si no hay TAVILY_API_KEY, el SDK no está instalado, o no hay resultados útiles,
retorna None → el frontend ofrece subir el reglamento manualmente (fallback).
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_RESULTADOS = 8
_MAX_CHARS = 18_000


def tavily_disponible() -> bool:
    return bool((os.getenv("TAVILY_API_KEY") or "").strip())


def buscar_reglamentos(universidad: str, nivel: str = "tesis") -> Optional[str]:
    """
    Busca en la web los reglamentos/lineamientos de investigación de la universidad.

    Args:
        universidad: nombre de la universidad (texto libre del estudiante).
        nivel:       "proyecto" | "tesis" | "maestría" | ...

    Returns:
        Texto concatenado de los reglamentos encontrados, o None si no hay nada útil.
    """
    api_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        logger.info("[web_search] TAVILY_API_KEY ausente — se omite la búsqueda.")
        return None

    try:
        from tavily import TavilyClient
    except Exception:
        logger.warning("[web_search] 'tavily-python' no instalado — se omite la búsqueda.")
        return None

    consulta = (
        f"universidad {universidad}: reglamento de grados y títulos, guía / esquema de "
        f"elaboración de {nivel} de investigación, estructura del proyecto, productos "
        f"observables, criterios de evaluación y rúbrica, normas de citación"
    )

    try:
        cliente = TavilyClient(api_key=api_key)
        resp = cliente.search(
            query=consulta,
            search_depth="advanced",
            max_results=_MAX_RESULTADOS,
            include_raw_content=True,
        )
    except Exception as exc:
        logger.warning(f"[web_search] Tavily falló: {exc}")
        return None

    resultados = (resp or {}).get("results") or []
    partes: list[str] = []
    chars = 0
    for r in resultados:
        contenido = (r.get("raw_content") or r.get("content") or "").strip()
        if not contenido:
            continue
        titulo = r.get("title", "")
        url = r.get("url", "")
        fragmento = f"[{titulo} — {url}]\n{contenido}"
        partes.append(fragmento[: _MAX_CHARS - chars])
        chars += len(fragmento)
        if chars >= _MAX_CHARS:
            break

    if not partes:
        logger.info(f"[web_search] Sin resultados útiles para '{universidad}'.")
        return None

    texto = "\n\n---\n\n".join(partes)
    logger.info(f"[web_search] {len(partes)} fuentes para '{universidad}' ({len(texto)} chars).")
    return texto
