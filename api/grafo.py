"""
Puente entre la API y el grafo LangGraph existente.

NO modifica la lógica del grafo: construye el mismo estado inicial que usaba
pantalla_seleccion.py de Streamlit y re-emite los updates de graph.stream()
como eventos para SSE, revisando el flag de cancelación entre nodos.
"""

import json
import logging
import os
import threading
from typing import Iterator, Optional

from config import Config

logger = logging.getLogger(__name__)

NODO_LABELS = {
    "nodo_supervisor":   "Supervisor",
    "nodo_redactor":     "Redactor",
    "nodo_auditor":      "Auditor",
    "nodo_metodologico": "Metodólogo",
    "nodo_debate":       "Debate (panel de 4 subagentes)",
    "nodo_consenso":     "Consenso",
    "nodo_disenso":      "Disenso",
    "nodo_exportador":   "Exportador",
}


def construir_estado_inicial(
    run_id: str,
    seccion: str,
    contexto_tesis: str,
    contexto_dependencias: str,
    contexto_teorico: str,
    rubrica_dinamica: Optional[dict],
    max_iteraciones: int,
    universidad: str = "upao",
    programa: str = "ingeniería de sistemas",
    modalidad: str = "tesis",
) -> dict:
    """Mismo estado inicial que usaba el frontend Streamlit."""
    return {
        "run_id":                      run_id,
        "universidad":                 universidad,
        "programa":                    programa,
        "modalidad":                   modalidad,
        "puntaje_inicial":             0.0,
        "seccion_objetivo":            seccion,
        "contexto_recuperado":         contexto_tesis,
        "contexto_dependencias":       contexto_dependencias,
        "contexto_teorico":            contexto_teorico,
        "rubrica_dinamica":            rubrica_dinamica,
        "max_iteraciones":             max_iteraciones,
        "siguiente_nodo":              "",
        "instrucciones_supervisor":    "",
        "pasos_ejecutados":            0,
        "max_pasos_red":               Config.get_max_pasos(max_iteraciones),
        "iter_auditada":               0,
        "iter_metodologica":           0,
        "iter_consenso":               0,
        "iter_disenso":                0,
        "plan_supervisor":             "",
        "texto_iterado":               "",
        "feedback_auditor":            "",
        "numero_iteracion":            0,
        "errores_rubrica":             [],
        "puntaje_estimado":            None,
        "observaciones_metodologicas": "",
        "resultado_consenso":          "",
        "resultado_disenso":           "",
        "debate_memory":               [],
        "debate_veredicto":            None,
        "debate_completado":           False,
        "historial_debate":            [],
        "_puntaje_max":                None,
        "consenso_matematico":         {},
        "scores_subagentes":           [],
        "consenso_matematico_auditor": {},
        "loras_activas":               [],
        "consenso_ejecutado":          False,
        "disenso_ejecutado":           False,
        "auditor_ejecutado":           False,
        "metodologo_ejecutado":        False,
        "debate_ejecutado":            False,
    }


def recuperar_contextos(doc, seccion: str) -> tuple[str, str, str]:
    """RAG de la sección + contexto cruzado + biblioteca, igual que Streamlit."""
    from backend.rag import (
        recuperar_contexto,
        recuperar_contexto_cruzado,
        recuperar_contexto_teorico,
    )
    from .deps import get_biblioteca

    contexto_tesis = recuperar_contexto(doc.vector_store, seccion)
    contexto_dependencias = recuperar_contexto_cruzado(doc.vector_store, seccion)
    contexto_teorico = recuperar_contexto_teorico(get_biblioteca(), seccion)
    return contexto_tesis, contexto_dependencias, contexto_teorico


def ejecutar_seccion(
    doc,
    seccion: str,
    max_iteraciones: int,
    thread_id: str,
    cancelar: threading.Event,
) -> Iterator[dict]:
    """
    Ejecuta el grafo completo sobre UNA sección, emitiendo eventos por nodo.
    El último evento es {"tipo": "seccion_completada", "resumen": {...}} o
    {"tipo": "cancelado"} si el usuario detuvo a los agentes.
    """
    from backend.graph.workflow import get_run_config
    from backend.rag.rag_context import set_vector_store
    from .deps import get_graph

    yield {"tipo": "fase", "fase": "rag", "detalle": f"Recuperando contexto de «{seccion}»…"}

    contexto_tesis, contexto_deps, contexto_teo = recuperar_contextos(doc, seccion)
    if not contexto_tesis.strip():
        yield {
            "tipo": "seccion_completada",
            "seccion": seccion,
            "resumen": {"vacia": True},
        }
        return

    estado_inicial = construir_estado_inicial(
        run_id=thread_id,
        seccion=seccion,
        contexto_tesis=contexto_tesis,
        contexto_dependencias=contexto_deps,
        contexto_teorico=contexto_teo,
        rubrica_dinamica=doc.rubrica,
        max_iteraciones=max_iteraciones,
    )

    graph = get_graph()
    run_config = get_run_config(thread_id)
    set_vector_store(doc.vector_store)

    yield {"tipo": "fase", "fase": "agentes", "detalle": "Red multiagente trabajando…"}

    cancelado = False
    for chunk in graph.stream(estado_inicial, run_config, stream_mode="updates"):
        for nodo, _ in chunk.items():
            yield {
                "tipo": "nodo",
                "seccion": seccion,
                "nodo": nodo,
                "label": NODO_LABELS.get(nodo, nodo),
            }
        if cancelar.is_set():
            cancelado = True
            break

    if cancelado:
        yield {"tipo": "cancelado", "seccion": seccion}
        return

    snapshot = graph.get_state(run_config)
    estado = snapshot.values if snapshot else {}

    errores = estado.get("errores_rubrica") or []
    resumen = {
        "seccion":            seccion,
        "puntaje":            estado.get("puntaje_estimado"),
        "puntaje_max":        estado.get("_puntaje_max"),
        "puntaje_inicial":    estado.get("puntaje_inicial"),
        "iteraciones":        estado.get("numero_iteracion"),
        "texto_mejorado":     estado.get("texto_iterado") or "",
        "puntos_debiles":     [e.get("descripcion", "") for e in errores][:6],
        "consenso":           (estado.get("resultado_consenso") or "")[:2500],
        "observaciones":      (estado.get("observaciones_metodologicas") or "")[:2500],
        "detalle":            _construir_detalle(estado, seccion, thread_id),
    }
    yield {"tipo": "seccion_completada", "seccion": seccion, "resumen": resumen}



def _leer_metricas(run_id: str) -> dict:
    """Métricas NLP que el nodo exportador ya calculó (eval_{run_id}.json)."""
    ruta = os.path.join(".", "outputs", f"eval_{run_id}.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f).get("metricas", {}) or {}
    except Exception:
        return {}


def _enriquecer_evaluacion(items: list) -> list:
    """Añade el texto del criterio UPAO a cada ítem evaluado."""
    from backend.config import RUBRICA_ITEMS_UPAO

    salida = []
    for it in items or []:
        num = it.get("item_numero")
        salida.append({
            "item_numero": num,
            "criterio":    RUBRICA_ITEMS_UPAO.get(num, ""),
            "puntaje":     it.get("puntaje", it.get("puntaje_actual", 0)),
            "observacion": it.get("observacion", it.get("descripcion", "")),
        })
    return salida


def _resumir_debate(estado: dict) -> dict:
    """Sesiones del panel de debate, acotadas para no inflar el payload."""
    sesiones = []
    for entrada in (estado.get("historial_debate") or [])[:4]:
        if not isinstance(entrada, dict):
            continue
        if entrada.get("tipo") == "panel":
            sesiones.append({
                "veredicto": entrada.get("veredicto", {}),
                "panel": [
                    {"subagente": p.get("subagente", ""), "contenido": (p.get("contenido") or "")[:1500]}
                    for p in (entrada.get("panel") or [])
                ],
            })
    if not sesiones and estado.get("debate_memory"):
        sesiones.append({
            "veredicto": estado.get("debate_veredicto") or {},
            "panel": [
                {"subagente": p.get("subagente", ""), "contenido": (p.get("contenido") or "")[:1500]}
                for p in (estado.get("debate_memory") or [])
            ],
        })
    return {"sesiones": sesiones}


def _construir_detalle(estado: dict, seccion: str, run_id: str) -> dict:
    """Payload completo para «Ver análisis completo» (equivale a pantalla_resultado)."""
    errores = estado.get("errores_rubrica") or []
    return {
        "run_id":            run_id,
        "seccion":           seccion,
        "puntaje":           estado.get("puntaje_estimado"),
        "puntaje_max":       estado.get("_puntaje_max"),
        "puntaje_inicial":   estado.get("puntaje_inicial"),
        "iteraciones":       estado.get("numero_iteracion"),
        "max_iteraciones":   estado.get("max_iteraciones"),
        "texto_mejorado":    estado.get("texto_iterado") or "",
        "feedback_auditor":  (estado.get("feedback_auditor") or "")[:4000],
        "observaciones_metodologicas": (estado.get("observaciones_metodologicas") or "")[:4000],
        "sugerencias_redactor": (estado.get("redactor_sugerencias_mejoras") or "")[:4000],
        "errores_rubrica": [
            {"item_numero": e.get("item_numero"), "puntaje_actual": e.get("puntaje_actual"),
             "descripcion": e.get("descripcion", "")}
            for e in errores
        ],
        "evaluacion_inicial": _enriquecer_evaluacion(estado.get("evaluacion_upao_inicial")),
        "evaluacion_final":   _enriquecer_evaluacion(estado.get("evaluacion_upao_final")),
        "consenso":          (estado.get("resultado_consenso") or "")[:4000],
        "disenso":           (estado.get("resultado_disenso") or "")[:4000],
        "debate":            _resumir_debate(estado),
        "contexto_pdf":      (estado.get("contexto_recuperado") or "")[:20000],
        "contexto_cruzado":  (estado.get("contexto_dependencias") or "")[:12000],
        "contexto_teorico":  (estado.get("contexto_teorico") or "")[:12000],
        "metricas":          _leer_metricas(run_id),
    }


def informe_secciones_md(resumenes: list[dict]) -> str:
    """Construye el informe markdown final para el modo 'secciones'."""
    partes: list[str] = []
    for r in resumenes:
        if r.get("vacia"):
            partes.append(
                f"## {r.get('seccion', 'Sección')}\n\n"
                "No encontré contenido redactado para esta sección en tu PDF. "
                "Puede que aún no la hayas escrito o que el texto no sea seleccionable.\n"
            )
            continue

        titulo = r["seccion"]
        puntaje = r.get("puntaje")
        pmax = r.get("puntaje_max")
        badge = f" — **{puntaje}/{pmax} pts**" if puntaje is not None and pmax else ""
        partes.append(f"## {titulo}{badge}\n")

        if r.get("puntos_debiles"):
            partes.append("**Puntos débiles detectados:**\n")
            partes.extend(f"- {p}" for p in r["puntos_debiles"])
            partes.append("")

        if r.get("consenso"):
            partes.append(f"**Síntesis del panel de agentes:**\n\n{r['consenso']}\n")

        if r.get("texto_mejorado"):
            partes.append(f"**Propuesta de texto mejorado:**\n\n{r['texto_mejorado']}\n")

    return "\n".join(partes).strip()
