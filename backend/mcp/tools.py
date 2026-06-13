"""
Herramientas MCP — funciones de fetch que enriquecen el contexto de cada subagente.

En lugar de bind_tools() (que requiere tool-calling loop y no es compatible con
with_structured_output en la misma llamada), las herramientas MCP se invocan como
funciones de pre-fetch: obtienen datos ANTES de que el subagente llame al LLM,
y los inyectan en el contexto del prompt. Esto es conceptualmente equivalente a MCP:
el agente "se conecta" a la fuente de datos y recibe su contenido.

Cada función retorna un dict que se mergea con inputs_base del subagente:
  {"rubrica_institucional_drive": "...", "contexto_mcp_extra": "..."}
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


McpFetchFn = Callable[[dict], dict]



def crear_drive_fetch_fn(folder_id_override: Optional[str] = None) -> McpFetchFn:
    """
    Retorna una función de fetch que obtiene la rúbrica institucional desde Google Drive.

    Si Drive no está disponible, retorna contexto vacío sin lanzar error.
    El subagente funciona con solo el contexto local en ese caso.

    Args:
        folder_id_override: ID de carpeta Drive específico para una universidad/programa.
                            Si None, usa DRIVE_ROOT_FOLDER_ID del .env.
    """
    from backend.mcp.drive_connector import get_drive_connector

    def _fetch_drive(inputs: dict) -> dict:
        connector = get_drive_connector()
        if not connector.disponible():
            return {}

        universidad = inputs.get("universidad", "upao")
        programa    = inputs.get("programa", "ingeniería de sistemas")

        rubrica = connector.obtener_rubrica(
            universidad=universidad,
            programa=programa,
            **({"root_folder_id": folder_id_override} if folder_id_override else {}),
        )

        if not rubrica:
            return {}

        logger.info(
            f"[MCP/Drive] Rúbrica obtenida para {universidad}/{programa} "
            f"({len(rubrica)} chars)"
        )
        return {"rubrica_institucional_drive": rubrica}

    return _fetch_drive



def crear_biblioteca_fetch_fn() -> McpFetchFn:
    """
    Retorna un fetch que formatea el contexto teórico de libros ya disponible en el estado.

    El contexto teórico (extraído de ChromaDB en el frontend) ya viaja en
    inputs_base["contexto_teorico"]. Esta herramienta lo resalta para que el
    subagente sepa explícitamente que tiene acceso a referencias bibliográficas.
    """
    def _fetch_biblioteca(inputs: dict) -> dict:
        ctx = inputs.get("contexto_teorico", "").strip()
        if not ctx:
            return {}
        return {
            "contexto_biblioteca_disponible": (
                f"[FUENTE MCP — BIBLIOTECA METODOLÓGICA]\n"
                f"Tienes acceso a los siguientes fragmentos de libros de metodología "
                f"relevantes para esta sección:\n\n{ctx}"
            )
        }
    return _fetch_biblioteca



def crear_tesis_fetch_fn() -> McpFetchFn:
    """
    Retorna un fetch que formatea el contexto de secciones relacionadas de la tesis.

    Útil para el Metodólogo de Coherencia y el Redactor, que necesitan ver
    cómo esta sección se relaciona con el resto del documento.
    """
    def _fetch_tesis(inputs: dict) -> dict:
        ctx = inputs.get("contexto_dependencias", "").strip()
        if not ctx:
            return {}
        return {
            "contexto_secciones_relacionadas": (
                f"[FUENTE MCP — SECCIONES RELACIONADAS DEL DOCUMENTO]\n"
                f"Contexto de otras secciones del trabajo de investigación "
                f"que son relevantes para evaluar coherencia cruzada:\n\n{ctx}"
            )
        }
    return _fetch_tesis



def componer_fetch_fns(*fns: Optional[McpFetchFn]) -> McpFetchFn:
    """
    Combina múltiples funciones de fetch en una sola.
    Las ejecuta en orden y mergea sus resultados.
    Si una falla, continúa con las siguientes.
    """
    fns_validas = [f for f in fns if f is not None]

    def _fetch_compuesto(inputs: dict) -> dict:
        resultado = {}
        for fn in fns_validas:
            try:
                parcial = fn(inputs) or {}
                resultado.update(parcial)
            except Exception as exc:
                logger.warning(f"[MCP/Compuesto] fetch parcial falló: {exc}")
        return resultado

    return _fetch_compuesto



def crear_fetch_para_lora(fuentes_datos: list[str], drive_folder_id: Optional[str] = None) -> Optional[McpFetchFn]:
    """
    Crea la función de fetch MCP apropiada según las fuentes_datos declaradas en el LoraConfig.

    Args:
        fuentes_datos:   Lista de strings del LoraConfig: ["biblioteca", "drive", "tesis"]
        drive_folder_id: Folder ID específico de la universidad (del YAML de universidad)

    Returns:
        McpFetchFn compuesta, o None si no hay fuentes declaradas.
    """
    if not fuentes_datos:
        return None

    fns = []

    if "drive" in fuentes_datos:
        fns.append(crear_drive_fetch_fn(folder_id_override=drive_folder_id))

    if "biblioteca" in fuentes_datos:
        fns.append(crear_biblioteca_fetch_fn())

    if "tesis" in fuentes_datos:
        fns.append(crear_tesis_fetch_fn())

    if not fns:
        return None

    if len(fns) == 1:
        return fns[0]

    return componer_fetch_fns(*fns)
