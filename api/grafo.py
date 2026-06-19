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
    perfil_institucional: Optional[str] = None,
    tipo_investigacion: Optional[str] = None,
    diseno: Optional[str] = None,
    meta_aprobacion: float = 0.90,
    modo_nucleo: bool = False,
    nucleo_plan: Optional[dict] = None,
) -> dict:
    """Mismo estado inicial que usaba el frontend Streamlit."""
    return {
        "modo_nucleo":                 modo_nucleo,
        "nucleo_plan":                 nucleo_plan,
        "run_id":                      run_id,
        "universidad":                 universidad,
        "programa":                    programa,
        "modalidad":                   modalidad,
        "perfil_institucional":        perfil_institucional,
        "tipo_investigacion":          tipo_investigacion,
        "diseno":                      diseno,
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
        "puntaje_previo":              None,
        "meta_aprobacion":             meta_aprobacion,
        "items_mejorables":            [],
        "items_na_tipo":               [],
        "contexto_coherencia":         None,
        "redactor_solo_pulido":        False,
        "mejor_texto":                 None,
        "mejor_puntaje":               None,
        "mejor_errores":               [],
        "mejor_eval_final":            [],
        "mejor_items_mejorables":      [],
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
    contexto_override: Optional[tuple] = None,
    modo_nucleo: bool = False,
    nucleo_plan: Optional[dict] = None,
    eval_override: Optional[dict] = None,
    metricas_juez: Optional[dict] = None,
) -> Iterator[dict]:
    """
    Ejecuta el grafo completo sobre UNA sección, emitiendo eventos por nodo.
    El último evento es {"tipo": "seccion_completada", "resumen": {...}} o
    {"tipo": "cancelado"} si el usuario detuvo a los agentes.

    `contexto_override` = (contexto_tesis, contexto_dependencias, contexto_teorico)
    permite pasar un contexto ya armado (p. ej. el núcleo de coherencia) en vez de
    recuperarlo por sección. `modo_nucleo` hace que el redactor entregue el texto
    mejorado por subpunto.
    """
    from backend.graph.workflow import get_run_config
    from backend.rag.rag_context import set_vector_store
    from .deps import get_graph

    from .tipo_investigacion import obtener_tipo_diseno

    tipo_inv, diseno = obtener_tipo_diseno(doc)

    yield {"tipo": "fase", "fase": "rag", "detalle": f"Recuperando contexto de «{seccion}»…"}

    if contexto_override is not None:
        contexto_tesis, contexto_deps, contexto_teo = contexto_override
    else:
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
        universidad=doc.universidad or "upao",
        programa=doc.programa or "ingeniería de sistemas",
        perfil_institucional=doc.perfil_institucional,
        tipo_investigacion=tipo_inv,
        diseno=diseno,
        modo_nucleo=modo_nucleo,
        nucleo_plan=nucleo_plan,
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
    puntaje = estado.get("puntaje_estimado")
    pmax    = estado.get("_puntaje_max")
    pini    = estado.get("puntaje_inicial")
    # El redactor solo REESCRIBE si el texto original no superaba el 90% de la
    # rúbrica; si lo superaba corre el "pulidor" y deja el texto tal cual.
    reescrito = bool(pmax) and pini is not None and (pini / pmax) <= 0.90
    cons = _secciones_consenso(estado.get("resultado_consenso") or "")
    from backend.rag import limpiar_marcas_rag
    resumen = {
        "seccion":            seccion,
        "puntaje":            puntaje,
        "puntaje_max":        pmax,
        "puntaje_inicial":    pini,
        "iteraciones":        estado.get("numero_iteracion"),
        "texto_mejorado":     limpiar_marcas_rag(estado.get("texto_iterado") or ""),
        "es_nucleo":          modo_nucleo,
        "reescrito":          reescrito,
        "solo_pulido":        bool(estado.get("redactor_solo_pulido")),
        "puntos_debiles":     [e.get("descripcion", "") for e in errores][:6],
        "fortalezas":         cons.get("fortalezas", ""),
        "recomendaciones":    (estado.get("redactor_sugerencias_mejoras") or "").strip(),
        "consenso":           (estado.get("resultado_consenso") or "")[:2500],
        "observaciones":      (estado.get("observaciones_metodologicas") or "")[:2500],
        "detalle":            _construir_detalle(estado, seccion, thread_id),
    }

    # En modo NÚCLEO mostramos las NOTAS REALES de la calificación (no el puntaje
    # propio del auditor, que evalúa todo el esqueleto junto y se infla). El texto
    # mejorado y la trazabilidad se conservan.
    if eval_override:
        resumen["puntaje"]         = eval_override.get("puntaje")
        resumen["puntaje_max"]     = eval_override.get("maximo")
        resumen["puntaje_inicial"] = eval_override.get("puntaje")
        det = resumen["detalle"]
        det["puntaje"]             = eval_override.get("puntaje")
        det["puntaje_inicial"]     = eval_override.get("puntaje")
        det["puntaje_max"]         = eval_override.get("maximo")
        det["evaluacion_inicial"]  = eval_override.get("items") or []
        det["evaluacion_final"]    = eval_override.get("items") or []

    # Métrica complementaria (rúbrica del tipo, LLM-as-judge) → pestaña Métricas del detalle.
    if metricas_juez:
        resumen["detalle"]["metricas_juez"] = metricas_juez

    yield {"tipo": "seccion_completada", "seccion": seccion, "resumen": resumen}



def _leer_metricas(run_id: str) -> dict:
    """Métricas NLP que el nodo exportador ya calculó (eval_{run_id}.json)."""
    ruta = os.path.join(".", "outputs", f"eval_{run_id}.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f).get("metricas", {}) or {}
    except Exception:
        return {}


def _enriquecer_evaluacion(items: list, rubrica: dict | None = None) -> list:
    """Añade el texto del criterio a cada ítem evaluado.

    Si hay rúbrica subida usa SUS descripciones; si no, la rúbrica oficial UPAO.
    """
    from backend.config import RUBRICA_ITEMS_UPAO
    from backend.rag.rubric_parser import texto_criterio_rubrica

    salida = []
    for it in items or []:
        num = it.get("item_numero")
        criterio = texto_criterio_rubrica(rubrica, num) if rubrica else RUBRICA_ITEMS_UPAO.get(num, "")
        salida.append({
            "item_numero": num,
            "criterio":    criterio,
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
    from backend.rag import limpiar_marcas_rag
    errores = estado.get("errores_rubrica") or []
    return {
        "run_id":            run_id,
        "seccion":           seccion,
        "puntaje":           estado.get("puntaje_estimado"),
        "puntaje_max":       estado.get("_puntaje_max"),
        "puntaje_inicial":   estado.get("puntaje_inicial"),
        "escala_max":        estado.get("escala_max", 5),
        "iteraciones":       estado.get("numero_iteracion"),
        "max_iteraciones":   estado.get("max_iteraciones"),
        "texto_mejorado":    limpiar_marcas_rag(estado.get("texto_iterado") or ""),
        "feedback_auditor":  (estado.get("feedback_auditor") or "")[:8000],
        "observaciones_metodologicas": (estado.get("observaciones_metodologicas") or "")[:12000],
        "sugerencias_redactor": (estado.get("redactor_sugerencias_mejoras") or "")[:8000],
        "errores_rubrica": [
            {"item_numero": e.get("item_numero"), "puntaje_actual": e.get("puntaje_actual"),
             "descripcion": e.get("descripcion", "")}
            for e in errores
        ],
        "evaluacion_inicial": _enriquecer_evaluacion(estado.get("evaluacion_upao_inicial"), estado.get("rubrica_dinamica")),
        "evaluacion_final":   _enriquecer_evaluacion(estado.get("evaluacion_upao_final"), estado.get("rubrica_dinamica")),
        "consenso":          (estado.get("resultado_consenso") or "")[:4000],
        "disenso":           (estado.get("resultado_disenso") or "")[:4000],
        "debate":            _resumir_debate(estado),
        "contexto_pdf":      (estado.get("contexto_recuperado") or "")[:20000],
        "contexto_cruzado":  (estado.get("contexto_dependencias") or "")[:12000],
        "contexto_teorico":  (estado.get("contexto_teorico") or "")[:12000],
        "metricas":          _leer_metricas(run_id),
    }


def _secciones_consenso(texto: str) -> dict:
    """Parsea la narrativa del consenso en sus bloques etiquetados.

    Devuelve solo lo que encuentre: {'acuerdos', 'fortalezas', 'prioridad'}.
    El detalle completo sigue disponible en «Ver análisis completo»; esto solo
    sirve para mostrar una síntesis limpia en el chat.
    """
    import re

    if not texto:
        return {}

    etiquetas = [
        ("acuerdos",   r"ACUERDOS DETECTADOS"),
        ("fortalezas", r"FORTALEZAS CONSENSUADAS"),
        ("prioridad",  r"PRIORIDAD DE CORRECCI[ÓO]N(?:\s+CONSENSUADA)?"),
    ]
    posiciones = []
    for clave, patron in etiquetas:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            posiciones.append((m.start(), m.end(), clave))
    posiciones.sort()

    out: dict[str, str] = {}
    for i, (_ini, fin, clave) in enumerate(posiciones):
        sig = posiciones[i + 1][0] if i + 1 < len(posiciones) else len(texto)
        cuerpo = texto[fin:sig].lstrip(" :*\n").rstrip(" *\n")
        if cuerpo:
            out[clave] = cuerpo
    return out


def _bloque_seccion_md(r: dict) -> str:
    """Bloque markdown LIMPIO de una sección para el chat (compartido por ambos modos)."""
    if r.get("vacia"):
        return (
            f"## {r.get('seccion', 'Sección')}\n\n"
            "No encontré contenido redactado para esta sección en tu PDF. "
            "Puede que aún no la hayas escrito o que el texto no sea seleccionable."
        )

    puntaje  = r.get("puntaje")
    pmax     = r.get("puntaje_max")
    pini     = r.get("puntaje_inicial")
    es_nucleo = bool(r.get("es_nucleo"))
    # El núcleo no lleva badge: su "nota" se mide contra criterios genéricos y no es
    # una calificación real (la calificación está en la tabla por ítem de la rúbrica).
    badge = ""
    if not es_nucleo and puntaje is not None and pmax:
        if pini is not None and round(pini) != round(puntaje):
            badge = f" — **{round(pini)} → {round(puntaje)}/{pmax} pts**"
        else:
            badge = f" — **{round(puntaje)}/{pmax} pts**"

    partes: list[str] = [f"## {r['seccion']}{badge}\n"]

    if r.get("fortalezas"):
        partes.append("**Fortalezas**\n")
        partes.append(r["fortalezas"])
        partes.append("")

    if r.get("puntos_debiles"):
        partes.append("**Puntos débiles**\n")
        partes.extend(f"- {p}" for p in r["puntos_debiles"])
        partes.append("")

    if r.get("recomendaciones"):
        partes.append("**Recomendaciones del mentor** (no se califican)\n")
        partes.append(r["recomendaciones"])
        partes.append("")

    if es_nucleo and r.get("texto_mejorado"):
        partes.append("**Texto mejorado y observaciones por subpunto**\n")
        partes.append(r["texto_mejorado"])
    elif r.get("reescrito") and r.get("texto_mejorado"):
        partes.append("**Propuesta de texto mejorado**\n")
        partes.append(r["texto_mejorado"])
    elif r.get("solo_pulido") and r.get("texto_mejorado"):
        partes.append("**Tu texto con los retoques de pulido aplicados** (ya estaba en nivel)\n")
        partes.append(r["texto_mejorado"])
    elif puntaje is not None and pmax:
        partes.append(
            f"_No reescribí el texto: tu versión ya alcanza el nivel requerido "
            f"({round(puntaje)}/{pmax})._"
        )
    else:
        partes.append("_No se generó una reescritura para esta sección._")

    return "\n".join(partes).strip()


def informe_secciones_md(resumenes: list[dict]) -> str:
    """Construye el informe markdown final para el modo 'secciones'."""
    return "\n\n---\n\n".join(_bloque_seccion_md(r) for r in resumenes).strip()
