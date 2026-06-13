"""
Nodo Humano (HITL pasarela) — Punto de revisión y aprobación del mentor.

El grafo se PAUSA automáticamente ANTES de ejecutar este nodo
gracias a `interrupt_before=["nodo_humano"]` en workflow.py.

Flujo HITL en Streamlit:
  1. graph.invoke() llega aquí y el grafo se detiene
  2. Streamlit lee el estado con graph.get_state(config)
  3. El mentor revisa, edita y aprueba/rechaza
  4. Streamlit llama a graph.update_state(config, {aprobacion_humana, texto_iterado})
  5. graph.invoke(None, config) reanuda → este nodo ejecuta → END

Al ejecutarse (post-aprobación), calcula y guarda las métricas de coherencia
en backend/logs/ para uso del investigador.
"""

import logging

from ..state import MentoriaState

logger = logging.getLogger(__name__)


def nodo_humano(state: MentoriaState) -> dict:
    """
    Nodo de revisión humana (Human-in-the-Loop).

    Registra la decisión que Streamlit inyectó con update_state(),
    y al completarse calcula las métricas de coherencia multiagente.
    """
    aprobacion = state.get("aprobacion_humana", "aprobado")
    logger.info(f"[Humano] Decisión registrada: {aprobacion}")

    rutas: list = []
    if aprobacion == "aprobado":
        try:
            from backend.metrics.coherencia import (
                calcular_y_guardar_coherencia,
                generar_transcripcion_debate,
            )
            estado_dict = dict(state)
            ruta_metricas = calcular_y_guardar_coherencia(estado_dict)
            ruta_debate   = generar_transcripcion_debate(estado_dict)
            rutas = [ruta_metricas, ruta_debate]
            logger.info(f"[Humano] Reportes generados → {rutas}")
        except Exception as exc:
            logger.warning(f"[Humano] No se pudieron generar reportes: {exc}")

    return {"aprobacion_humana": aprobacion, "rutas_reportes": rutas or None}
