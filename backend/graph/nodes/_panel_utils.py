"""
Utilidades de ejecución de panel de subagentes con memoria compartida intra-nodo.

CONCEPTO (explicado por el profesor):
  "Para cada nodo, hacer un montón de subagentes que debatan,
   pero no mediante PROMTs, mediante algoritmos."

El debate entre subagentes funciona así:
  1. Sub1 evalúa el texto → genera output
  2. Sub2 evalúa el mismo texto PERO TAMBIÉN VE el output de Sub1 (memoria compartida)
  3. Sub3 (si existe) ve los outputs de Sub1 y Sub2
  4. El consenso entre todos se calcula ALGORÍTMICAMENTE (std_dev, media, moda)
     — no por LLM, exactamente como pidió el profesor.

La "memoria compartida" es el historial_panel: lista de outputs anteriores
que se inyecta en el prompt del siguiente subagente como contexto adicional.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from ._utils import invocar_con_backoff, calcular_consenso_matematico

logger = logging.getLogger(__name__)

McpFetchFn = Callable[[dict], dict]



@dataclass
class ResultadoSubagente:
    lora_id:      str
    output:       Any
    contexto_mcp: dict = field(default_factory=dict)
    error:        Optional[str] = None

    @property
    def exitoso(self) -> bool:
        return self.output is not None and self.error is None



def ejecutar_panel(
    sub_items:     list[tuple],
    inputs_base:   dict,
    logger_prefix: str = "Panel",
    pausa_entre_subs: float = 2.0,
) -> list[ResultadoSubagente]:
    """
    Ejecuta un panel de subagentes secuencialmente con memoria compartida.

    Cada subagente:
      1. Recibe inputs_base (contexto del estado)
      2. Recibe el historial de outputs anteriores del panel (memoria compartida)
      3. Opcionalmente llama a su función MCP fetch para enriquecer el contexto
      4. Genera su evaluación

    Args:
        sub_items:         Lista de (chain, lora_id, mcp_fetch_fn).
                           mcp_fetch_fn puede ser None si el subagente no usa MCP.
        inputs_base:       Diccionario con el contexto base (del estado del grafo).
        logger_prefix:     Prefijo para los logs (identifica qué nodo está ejecutando).
        pausa_entre_subs:  Segundos de pausa entre subagentes (anti-rate-limit Groq).

    Returns:
        Lista de ResultadoSubagente en el mismo orden que sub_items.
    """
    resultados: list[ResultadoSubagente] = []
    historial_panel: list[str] = []

    for i, (chain, lora_id, mcp_fetch_fn) in enumerate(sub_items):
        inputs = dict(inputs_base)
        inputs["historial_panel"] = (
            "\n\n".join(historial_panel)
            if historial_panel
            else "Eres el primer evaluador del panel — no hay evaluaciones anteriores que considerar."
        )

        contexto_mcp = {}
        if mcp_fetch_fn is not None:
            try:
                contexto_mcp = mcp_fetch_fn(inputs) or {}
                inputs.update(contexto_mcp)
                if contexto_mcp:
                    logger.debug(
                        f"[{logger_prefix}/{lora_id}] MCP enriqueció contexto con "
                        f"{list(contexto_mcp.keys())}"
                    )
            except Exception as exc:
                logger.warning(f"[{logger_prefix}/{lora_id}] MCP fetch falló (continuando): {exc}")

        if i > 0:
            time.sleep(pausa_entre_subs)

        try:
            output = invocar_con_backoff(chain, inputs)

            resumen = _resumir_output_para_historial(lora_id, output)
            historial_panel.append(resumen)

            resultados.append(ResultadoSubagente(
                lora_id=lora_id,
                output=output,
                contexto_mcp=contexto_mcp,
            ))
            logger.info(f"[{logger_prefix}/{lora_id}] ✓ completado")

        except Exception as exc:
            logger.warning(f"[{logger_prefix}/{lora_id}] Falló: {exc}")
            resultados.append(ResultadoSubagente(
                lora_id=lora_id,
                output=None,
                error=str(exc),
            ))

    exitosos = sum(1 for r in resultados if r.exitoso)
    logger.info(f"[{logger_prefix}] Panel completo: {exitosos}/{len(resultados)} subagentes exitosos")
    return resultados


def _resumir_output_para_historial(lora_id: str, output: Any) -> str:
    """
    Genera un resumen del output de un subagente para inyectar en el siguiente.
    Es el mecanismo de 'memoria compartida intra-nodo'.
    """
    prefijo = f"[Evaluador anterior: {lora_id}]"

    if output is None:
        return f"{prefijo} No disponible (falló)."

    if hasattr(output, "puntaje_total") and hasattr(output, "feedback_general"):
        items_con_error = [
            i for i in getattr(output, "items_evaluados", [])
            if getattr(i, "puntaje", 3) < 2
        ]
        return (
            f"{prefijo}\n"
            f"  Puntaje: {output.puntaje_total} | Aprobado: {output.aprobado}\n"
            f"  Ítems con error ({len(items_con_error)}): "
            f"{[i.item_numero for i in items_con_error]}\n"
            f"  Feedback: {output.feedback_general[:300]}..."
        )

    if hasattr(output, "posicion_metodologica"):
        return (
            f"{prefijo}\n"
            f"  Posición: {output.posicion_metodologica[:300]}...\n"
            f"  Confirmados: {getattr(output, 'items_confirmados', [])}\n"
            f"  Descartados: {getattr(output, 'items_descartados', [])}"
        )

    if hasattr(output, "content"):
        return f"{prefijo}\n  {output.content[:400]}..."

    return f"{prefijo}\n  {str(output)[:400]}"



def consolidar_panel_evaluador(
    resultados:      list[ResultadoSubagente],
    extraer_score:   Callable[[Any], float],
    extraer_items:   Callable[[Any], list],
    puntaje_max:     float,
    umbral_std:      Optional[float] = None,
) -> dict:
    """
    Consolida resultados de un panel de evaluadores mediante algoritmos determinísticos.

    El debate ocurrió durante la ejecución del panel (cada sub vio al anterior).
    Este paso DECIDE el resultado final algorítmicamente, sin LLM adicional.

    Algoritmos usados:
      - std_dev + media para consenso de scores
      - Votación por mayoría (≥ N-1 subagentes) para errores

    Args:
        resultados:    Lista de ResultadoSubagente del panel
        extraer_score: fn(output) → float
        extraer_items: fn(output) → List[dict o Pydantic item]
        puntaje_max:   Puntaje máximo posible (para calcular umbral dinámico)
        umbral_std:    Umbral de std_dev para consenso (default: 0.4 * puntaje_max / 3)

    Returns:
        dict con: score_final, scores_subagentes, errores_consensuados,
                  consenso_matematico, n_validos
    """
    validos = [r for r in resultados if r.exitoso]
    if not validos:
        logger.error("[Panel] Ningún subagente exitoso — retornando resultado vacío")
        return {
            "score_final": 0,
            "scores_subagentes": [],
            "errores_consensuados": [],
            "consenso_matematico": {"hay_consenso": False, "motivo": "ningún subagente exitoso"},
            "n_validos": 0,
        }

    scores = []
    for r in validos:
        try:
            scores.append(float(extraer_score(r.output)))
        except Exception as exc:
            logger.warning(f"[Panel] extraer_score falló para {r.lora_id}: {exc}")

    umbral = umbral_std if umbral_std is not None else (0.4 * puntaje_max / 3)
    consenso = calcular_consenso_matematico(scores, umbral_std=umbral)
    score_final = int(round(consenso["score_consenso"])) if scores else 0

    todos_items: list = []
    for r in validos:
        try:
            items = extraer_items(r.output) or []
            todos_items.extend(items)
        except Exception as exc:
            logger.warning(f"[Panel] extraer_items falló para {r.lora_id}: {exc}")

    conteo: dict[int, list] = {}
    for item in todos_items:
        num = _extraer_numero_item(item)
        if num is not None:
            conteo.setdefault(num, []).append(item)

    umbral_errores = max(2, len(validos) - 1)
    errores_consensuados = []
    for num, items in conteo.items():
        if len(items) >= umbral_errores:
            item = items[0]
            errores_consensuados.append({
                "item_numero":    num,
                "puntaje_actual": _calcular_puntaje_promedio(items),
                "descripcion":    _extraer_descripcion(item),
            })

    logger.info(
        f"[Panel] Consolidado: score={score_final}/{puntaje_max} | "
        f"errores={len(errores_consensuados)} (de {len(conteo)} candidatos) | "
        f"{consenso['motivo']}"
    )

    return {
        "score_final":         score_final,
        "scores_subagentes":   scores,
        "errores_consensuados": errores_consensuados,
        "consenso_matematico": consenso,
        "n_validos":           len(validos),
    }



def consolidar_panel_escritor(resultados: list[ResultadoSubagente]) -> str:
    """
    Para paneles de escritura, retorna el texto del ÚLTIMO subagente exitoso.

    El Redactor usa un pipeline secuencial:
      Sub1 (corrector) → genera texto corregido
      Sub2 (integrador) → ve el texto de Sub1 en historial_panel y lo refina

    El texto final es siempre el del integrador (Sub2), que ya incorporó
    el trabajo de Sub1. No hay consenso numérico — el 2do subagente es el árbitro.
    """
    validos = [r for r in resultados if r.exitoso]
    if not validos:
        return ""

    ultimo = validos[-1]
    if hasattr(ultimo.output, "content"):
        return ultimo.output.content.strip()
    return str(ultimo.output).strip()


def consolidar_panel_texto(resultados: list[ResultadoSubagente], separador: str = "\n\n---\n\n") -> str:
    """
    Para paneles que producen texto libre (Metodólogo, Disenso).
    Concatena los outputs de todos los subagentes exitosos.
    Cada perspectiva aporta su dimensión de análisis.
    """
    partes = []
    for r in resultados:
        if not r.exitoso:
            continue
        if hasattr(r.output, "content"):
            texto = r.output.content.strip()
        else:
            texto = str(r.output).strip()
        if texto:
            partes.append(f"**[{r.lora_id}]**\n{texto}")

    return separador.join(partes) if partes else ""



def _extraer_numero_item(item: Any) -> Optional[int]:
    if isinstance(item, dict):
        return item.get("item_numero")
    return getattr(item, "item_numero", None)


def _calcular_puntaje_promedio(items: list) -> int:
    puntajes = []
    for item in items:
        if isinstance(item, dict):
            puntajes.append(item.get("puntaje_actual", item.get("puntaje", 0)))
        else:
            puntajes.append(getattr(item, "puntaje", 0))
    return round(sum(puntajes) / len(puntajes)) if puntajes else 0


def _extraer_descripcion(item: Any) -> str:
    if isinstance(item, dict):
        return item.get("descripcion", item.get("observacion", ""))
    return getattr(item, "observacion", getattr(item, "descripcion", ""))
