"""Genera un reporte Markdown legible a partir del JSON de las nuevas métricas del evaluador."""

import json
from pathlib import Path

def generar_reporte(ruta_eval_json: str) -> str:
    """Lee eval_{run_id}.json y devuelve un string Markdown con las nuevas métricas."""
    with open(ruta_eval_json, "r", encoding="utf-8") as f:
        datos = json.load(f)

    metricas = datos.get("metricas", {})
    run_id = datos.get("run_id", "?")
    universidad = datos.get("universidad", "?")
    arquitectura = datos.get("arquitectura", "?")

    llm_score = metricas.get("llm_judge_score", 0.0)
    llm_max = metricas.get("llm_judge_max", 0.0)
    llm_pct = metricas.get("llm_judge_pct", 0.0)
    
    gain_score = metricas.get("gain_score", 0.0)
    gain_interp = metricas.get("gain_score_interpretacion", "N/A")
    gain_pre = metricas.get("gain_score_pre", 0.0)
    gain_post = metricas.get("gain_score_post", 0.0)

    sim_cos = metricas.get("similitud_coseno", 0.0)
    sim_interp = metricas.get("similitud_coseno_interpretacion", "N/A")

    ctx_prec = metricas.get("context_precision", 0.0)
    ctx_totales = metricas.get("context_precision_chunks_totales", 0)
    ctx_relevantes = metricas.get("context_precision_chunks_relevantes", 0)
    ctx_interp = metricas.get("context_precision_interpretacion", "N/A")

    trajectory = metricas.get("iterative_consistency", [])
    has_iter = metricas.get("iterative_consistency_has_iter", False)

    lineas = [
        f"# Reporte de Calidad y Métricas Académicas — {run_id}",
        f"",
        f"**Universidad:** {universidad}  ",
        f"**Arquitectura:** {arquitectura}  ",
        f"",
        f"## 📊 Métricas de Calidad Académica",
        f"",
        f"| Métrica | Valor | Interpretación | Detalles |",
        f"| :--- | :--- | :--- | :--- |",
        f"| **LLM-as-Judge (G-Eval)** | **{llm_score}/{llm_max}** ({llm_pct:.1%}) | Calidad Metodológica Global | Evaluado con rúbrica especializada por panel de jueces |",
        f"| **Gain Score** | **{gain_score:+.4f}** | {gain_interp.title()} | Delta pre ({gain_pre}) → post ({gain_post}) según Juez LLM |",
        f"| **Similitud Coseno (e5)** | **{sim_cos:.4f}** | {sim_interp} | Guardrail semántico utilizando multilingual-e5-small |",
        f"| **Context Precision** | **{ctx_prec:.4f}** | {ctx_interp} | {ctx_relevantes}/{ctx_totales} chunks de libros recuperados relevantes |",
    ]

    if has_iter:
        trajectory_str = " ➔ ".join(str(s) for s in trajectory)
        lineas.append(
            f"| **Iterative Consistency** | **{trajectory_str}** | Trayectoria de mejora | Calificación del juez externo por iteración |"
        )

    lineas += [
        f"",
        f"---",
        f"",
        f"## 📋 Detalle de la Evaluación del Juez LLM",
        f"",
    ]

    secciones_sel = metricas.get("llm_judge_secciones", [])
    if secciones_sel:
        lineas.append(f"**Secciones de la Rúbrica Especializada Aplicadas:** {', '.join(secciones_sel)}  ")
        lineas.append("")

    items_evaluados = metricas.get("llm_judge_items", [])
    if items_evaluados:
        lineas += [
            f"| Ítem ID | Criterio de la Rúbrica | Pts Asignados | Pts Máx | Justificación Académica |",
            f"| :--- | :--- | :--- | :--- | :--- |",
        ]
        for item in items_evaluados:
            item_id = item.get("item_id", "?")
            desc = item.get("descripcion", "Sin descripción")
            pts_ob = item.get("pts_obtenido", 0.0)
            pts_mx = item.get("pts_max", 0.0)
            razon = item.get("razon", "Sin justificación")
            lineas.append(f"| {item_id} | {desc} | **{pts_ob}** | {pts_mx} | {razon} |")
    else:
        lineas.append("_(No hay detalles de ítems evaluados disponibles)_")

    lineas.append("")
    return "\n".join(lineas)

def guardar_reporte(ruta_eval_json: str, ruta_salida: str | None = None) -> str:
    md = generar_reporte(ruta_eval_json)
    if ruta_salida is None:
        ruta_salida = ruta_eval_json.replace(".json", "_reporte.md")
    Path(ruta_salida).write_text(md, encoding="utf-8")
    return ruta_salida
