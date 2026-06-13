"""
Evaluador determinístico de calidad de tesis — calcula las nuevas 5 métricas:
1. LLM-as-judge (G-Eval style): calidad metodológica sobre el texto final con la rúbrica especializada.
2. Gain Score: mejora neta pre→post calculada sobre las puntuaciones del LLM-judge.
3. Cosine Similarity (multilingual-e5): guardrail semántico para preservar significado.
4. Context Precision: relevancia de los chunks recuperados de libros.
5. Iterative Consistency: trayectoria del score del juez externo (si hay >=2 iteraciones).
"""

import json
import logging
import sys
import os
from pathlib import Path

from .metrics.cosine_sim import calcular_similitud_coseno
from .metrics.context_precision import calcular_context_precision
from .metrics.llm_judge import evaluar_con_juez_llm

logger = logging.getLogger(__name__)

def evaluar_desde_archivo(ruta_json: str) -> dict:
    with open(ruta_json, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return evaluar(datos)

def evaluar(datos: dict) -> dict:
    texto_inicial = datos.get("texto_inicial", "")
    texto_final = datos.get("texto_final", "")
    if not texto_final or not texto_final.strip():
        texto_final = texto_inicial
    seccion_objetivo = datos.get("seccion_objetivo", "")
    contexto_teorico = datos.get("contexto_teorico", "")
    historial_textos = datos.get("historial_textos", [])

    logger.info(f"[Evaluator] Iniciando evaluación de run_id={datos.get('run_id')}...")

    try:
        eval_final = evaluar_con_juez_llm(seccion_objetivo, texto_final, es_panel=True)
    except Exception as exc:
        logger.error(f"[Evaluator] Error en LLM-as-judge final: {exc}")
        from .metrics.llm_judge import EvaluacionSeccion
        eval_final = EvaluacionSeccion(
            secciones_seleccionadas=[],
            items=[],
            puntaje_total=0.0,
            puntaje_maximo=1.0
        )

    try:
        if texto_inicial.strip() and texto_inicial != texto_final:
            eval_inicial = evaluar_con_juez_llm(seccion_objetivo, texto_inicial, es_panel=False)
            
            ids_comunes = {item.item_id for item in eval_final.items} & {item.item_id for item in eval_inicial.items}
            
            if ids_comunes:
                pts_ini = sum(item.pts_obtenido for item in eval_inicial.items if item.item_id in ids_comunes)
                pts_fin = sum(item.pts_obtenido for item in eval_final.items if item.item_id in ids_comunes)
                pts_max = sum(item.pts_max for item in eval_final.items if item.item_id in ids_comunes)
            else:
                pts_ini = eval_inicial.puntaje_total
                pts_fin = eval_final.puntaje_total
                pts_max = eval_final.puntaje_maximo
        else:
            pts_ini = eval_final.puntaje_total
            pts_fin = eval_final.puntaje_total
            pts_max = eval_final.puntaje_maximo
    except Exception as exc:
        logger.warning(f"[Evaluator] Error en LLM-as-judge inicial: {exc}")
        pts_ini = eval_final.puntaje_total
        pts_fin = eval_final.puntaje_total
        pts_max = eval_final.puntaje_maximo

    if pts_max > pts_ini:
        gain = (pts_fin - pts_ini) / (pts_max - pts_ini)
    else:
        gain = 0.0

    gain_interpretacion = (
        "mejora alta" if gain > 0.6
        else "mejora moderada" if gain > 0.3
        else "mejora baja" if gain > 0.0
        else "sin cambio" if gain == 0.0
        else "regresión"
    )

    try:
        sim_cos = calcular_similitud_coseno(texto_inicial, texto_final)
    except Exception as exc:
        logger.warning(f"[Evaluator] Error en Cosine Similarity: {exc}")
        sim_cos = {"similitud_coseno": 0.0, "interpretacion": f"Error: {exc}"}

    try:
        ctx_precision = calcular_context_precision(seccion_objetivo, contexto_teorico, texto_final)
    except Exception as exc:
        logger.warning(f"[Evaluator] Error en Context Precision: {exc}")
        ctx_precision = {"context_precision": 0.0, "chunks_totales": 0, "chunks_relevantes": 0, "interpretacion": f"Error: {exc}"}

    trajectory = []
    has_iter = False
    if isinstance(historial_textos, list) and len(historial_textos) >= 3:
        has_iter = True
        logger.info(f"[Evaluator] Calculando Iterative Consistency para {len(historial_textos)} versiones de texto...")
        for idx, t in enumerate(historial_textos):
            try:
                eval_t = evaluar_con_juez_llm(seccion_objetivo, t, es_panel=False)
                trajectory.append(eval_t.puntaje_total)
            except Exception as exc:
                logger.warning(f"[Evaluator] Error evaluando iteración {idx} para consistencia: {exc}")
                trajectory.append(0.0)

    resultado = {
        "run_id": datos.get("run_id"),
        "arquitectura": datos.get("arquitectura"),
        "universidad": datos.get("universidad"),
        "metricas": {
            "llm_judge_score": eval_final.puntaje_total,
            "llm_judge_max": eval_final.puntaje_maximo,
            "llm_judge_pct": round((eval_final.puntaje_total / eval_final.puntaje_maximo) if eval_final.puntaje_maximo > 0 else 0.0, 4),
            "llm_judge_secciones": eval_final.secciones_seleccionadas,
            "llm_judge_items": [item.model_dump() for item in eval_final.items],
            
            "gain_score": round(gain, 4),
            "gain_score_interpretacion": gain_interpretacion,
            "gain_score_pre": pts_ini,
            "gain_score_post": pts_fin,
            
            "similitud_coseno": sim_cos["similitud_coseno"],
            "similitud_coseno_interpretacion": sim_cos["interpretacion"],
            
            "context_precision": ctx_precision["context_precision"],
            "context_precision_chunks_totales": ctx_precision["chunks_totales"],
            "context_precision_chunks_relevantes": ctx_precision["chunks_relevantes"],
            "context_precision_interpretacion": ctx_precision["interpretacion"],
            
            "iterative_consistency": trajectory,
            "iterative_consistency_has_iter": has_iter
        }
    }

    ruta_salida = Path("./outputs") / f"eval_{datos.get('run_id', 'sin_id')}.json"
    ruta_salida.parent.mkdir(exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    logger.info(f"[Evaluator] Evaluación guardada en {ruta_salida}")
    return resultado

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m evaluator.evaluator <ruta_json>")
        sys.exit(1)
    resultado = evaluar_desde_archivo(sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
