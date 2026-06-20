"""
Nodo Exportador — Serializa el MentoriaState final a JSON y lo persiste.

Corre una sola vez, justo antes de END. No usa LLM.
Guarda localmente en ./outputs/run_{run_id}.json.
Si GCS_BUCKET_NAME está definido, también sube a Google Cloud Storage.

Debate como embeddings:
  Cada entrada de debate_memory ({"subagente": str, "contenido": str}) se vectoriza
  y guarda en ChromaDB colección "debate_history" con metadata.subagente.
  Esto permite calcular cosine similarity entre perspectivas del panel y recuperar
  debates similares en el futuro.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from ..state import MentoriaState

logger = logging.getLogger(__name__)

_PROJECT_ROOT       = Path(__file__).resolve().parent.parent.parent.parent
_OUTPUTS_DIR        = _PROJECT_ROOT / "outputs"
_DEBATE_CHROMA_PATH = str(_PROJECT_ROOT / "chroma_db" / "debate_history")
_DEBATE_COLLECTION  = "debate_history"


def _serializar_historial(historial: list) -> list[str]:
    """Convierte cada entrada del historial de debate en un string legible.

    Soporta el nuevo formato de panel ({"tipo": "panel", "panel": [...], "veredicto": {...}})
    y el formato anterior por compatibilidad.
    """
    turnos = []
    for entrada in historial:
        if not isinstance(entrada, dict):
            turnos.append(str(entrada))
            continue

        if entrada.get("tipo") == "panel":
            for item in entrada.get("panel", []):
                sub  = item.get("subagente", "?")
                cont = item.get("contenido", "")
                if cont:
                    turnos.append(f"[Debate/{sub}] {cont}")
            veredicto = entrada.get("veredicto", {})
            if veredicto:
                turnos.append(
                    f"[Veredicto] {veredicto.get('veredicto_general', '')} — "
                    f"{veredicto.get('justificacion', '')}"
                )
        else:
            n    = entrada.get("ronda", "?")
            arg  = entrada.get("argumento_auditor", "")
            resp = entrada.get("respuesta_metodologico", "")
            if arg:
                turnos.append(f"[Ronda {n} — Auditor] {arg}")
            if resp:
                turnos.append(f"[Ronda {n} — Metodólogo] {resp}")

    return turnos


def _subir_a_gcs(ruta_local: Path, blob_name: str) -> None:
    bucket_name = os.environ.get("GCS_BUCKET_NAME")
    if not bucket_name:
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob   = bucket.blob(blob_name)
        blob.upload_from_filename(str(ruta_local))
        logger.info(f"[Exportador] Subido a GCS: gs://{bucket_name}/{blob_name}")
    except Exception as exc:
        logger.warning(f"[Exportador] No se pudo subir a GCS ({blob_name}): {exc}")


def make_nodo_exportador():
    """Fábrica del Nodo Exportador. No recibe LLM."""

    def nodo_exportador(state: MentoriaState) -> dict:
        run_id = state.get("run_id") or "sin_id"
        logger.info(f"[Exportador] Serializando estado — run_id={run_id}")

        historial_raw  = state.get("historial_debate") or []
        errores_raw    = state.get("errores_rubrica") or []
        debate_memory  = state.get("debate_memory") or []
        debate_vered   = state.get("debate_veredicto") or {}

        payload = {
            "run_id":    run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "universidad": state.get("universidad", ""),
            "programa":    state.get("programa", ""),
            "tipo_investigacion": state.get("tipo_investigacion"),
            "diseno":             state.get("diseno"),
            "arquitectura": "langgraph-hub-spoke",
            "seccion_objetivo": state.get("seccion_objetivo", ""),
            "contexto_teorico": state.get("contexto_teorico", ""),
            "texto_inicial": state.get("contexto_recuperado", ""),
            "texto_final":   state.get("texto_iterado", ""),
            "puntaje_inicial": state.get("puntaje_inicial", 0.0),
            "puntaje_final":   state.get("puntaje_estimado"),
            "puntaje_maximo":  state.get("_puntaje_max"),
            "iteraciones_realizadas": state.get("numero_iteracion", 0),
            "historial_debate": _serializar_historial(historial_raw),
            "debate_veredicto": debate_vered,
            "errores_detectados": [
                e.get("descripcion", str(e)) if isinstance(e, dict) else str(e)
                for e in errores_raw
            ],
            "resultado_consenso": state.get("resultado_consenso", ""),
            "resultado_disenso":  state.get("resultado_disenso", ""),
            "redactor_evaluacion_rubrica": state.get("redactor_evaluacion_rubrica"),
            "redactor_sugerencias_mejoras": state.get("redactor_sugerencias_mejoras"),
            "historial_textos": state.get("historial_textos"),
            "historial_puntajes_rubrica": state.get("historial_puntajes_rubrica"),
            "evaluacion_upao_inicial": state.get("evaluacion_upao_inicial"),
            "evaluacion_upao_final": state.get("evaluacion_upao_final"),

            "metadata": {
                "max_iterations": state.get("max_iteraciones"),
                "modelo_llm":     "llama-3.3-70b-versatile",
                "temperatura_auditor":  0.1,
                "temperatura_redactor": 0.4,
            },
        }

        _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        ruta = _OUTPUTS_DIR / f"run_{run_id}.json"
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"[Exportador] Guardado en {ruta}")

        ruta_debate_md = _OUTPUTS_DIR / f"debate_{run_id}.md"
        _generar_reporte_debate(payload, historial_raw, state, ruta_debate_md)
        logger.info(f"[Exportador] Reporte debate en {ruta_debate_md}")

        ruta_eval    = None
        ruta_reporte = None
        # En modo NÚCLEO (subcorrida interna de la revisión completa) NO se corren las
        # métricas NLP ni el juez LLM: es cómputo desperdiciado (la calificación real
        # sale del barrido por ítem, no de esta subcorrida).
        if state.get("modo_nucleo"):
            logger.info("[Exportador] modo núcleo — se omiten métricas NLP/juez (subcorrida interna).")
        else:
            try:
                from evaluator.evaluator import evaluar_desde_archivo
                from evaluator.report import guardar_reporte

                evaluar_desde_archivo(str(ruta))
                ruta_eval    = _OUTPUTS_DIR / f"eval_{run_id}.json"
                ruta_reporte = guardar_reporte(str(ruta_eval))

                logger.info(f"[Exportador] Métricas en {ruta_eval} | Reporte en {ruta_reporte}")
            except Exception as exc:
                logger.warning(f"[Exportador] No se pudieron generar métricas NLP: {exc}")

        _subir_a_gcs(ruta, f"runs/run_{run_id}.json")
        _subir_a_gcs(ruta_debate_md, f"runs/debate_{run_id}.md")
        if ruta_eval and Path(str(ruta_eval)).exists():
            _subir_a_gcs(ruta_eval, f"runs/eval_{run_id}.json")
        if ruta_reporte and Path(ruta_reporte).exists():
            _subir_a_gcs(Path(ruta_reporte), f"runs/eval_{run_id}_reporte.md")

        _guardar_debate_como_embeddings(
            debate_memory=debate_memory,
            historial=historial_raw,
            run_id=run_id,
            universidad=state.get("universidad", ""),
            programa=state.get("programa", ""),
            seccion=state.get("seccion_objetivo", ""),
        )

        rutas: list[str] = [str(ruta), str(ruta_debate_md)]
        if ruta_eval and Path(str(ruta_eval)).exists():
            rutas.append(str(ruta_eval))
        if ruta_reporte and Path(str(ruta_reporte)).exists():
            rutas.append(str(ruta_reporte))

        return {"rutas_reportes": rutas}

    return nodo_exportador



def _generar_reporte_debate(payload: dict, historial: list, state: dict, ruta: Path) -> None:
    run_id      = payload.get("run_id", "?")[:8]
    timestamp   = payload.get("timestamp", "")
    universidad = payload.get("universidad", "—")
    programa    = payload.get("programa", "—")
    seccion     = state.get("seccion_objetivo", "—")
    pts_ini     = payload.get("puntaje_inicial", 0)
    pts_fin     = payload.get("puntaje_final", "—")
    n_iter      = payload.get("iteraciones_realizadas", 0)
    errores     = payload.get("errores_detectados", [])

    lineas = [
        f"# Reporte de Mentoría — {run_id}",
        f"",
        f"| Campo | Valor |",
        f"|-------|-------|",
        f"| Fecha | {timestamp} |",
        f"| Universidad | {universidad} |",
        f"| Programa | {programa} |",
        f"| Sección evaluada | {seccion} |",
        f"| Puntaje inicial | {pts_ini} |",
        f"| Puntaje final | {pts_fin} |",
        f"| Iteraciones realizadas | {n_iter} |",
        f"",
        f"## Errores Detectados por el Auditor",
        f"",
    ]
    if errores:
        for err in errores:
            lineas.append(f"- {err}")
    else:
        lineas.append("_(Sin errores confirmados — texto aprobado directamente)_")

    lineas += [f"", f"## Historial de Debate ({len(historial)} sesión(es))", f""]

    for idx, entrada in enumerate(historial, 1):
        if not isinstance(entrada, dict):
            continue

        if entrada.get("tipo") == "panel":
            veredicto  = entrada.get("veredicto", {})
            vered_gen  = veredicto.get("veredicto_general", "—")
            confirmados = veredicto.get("items_confirmados", [])
            descartados = veredicto.get("items_descartados", [])
            matizados   = veredicto.get("items_matizados", [])

            lineas += [
                f"### Sesión de debate {idx} (panel de 4 subagentes)",
                f"",
                f"> **Veredicto general:** {vered_gen}  ",
                f"> **Confirmados:** {confirmados} | **Descartados:** {descartados} | **Matizados:** {matizados}",
                f"",
                f"**Justificación:** {veredicto.get('justificacion', '—')}",
                f"",
            ]
            for item in entrada.get("panel", []):
                sub  = item.get("subagente", "?")
                cont = item.get("contenido", "—")
                lineas += [f"**[{sub}]**", f"", cont, f""]
            lineas.append("---")
            lineas.append("")
        else:
            n           = entrada.get("ronda", idx)
            confirmados = entrada.get("items_confirmados", [])
            descartados = entrada.get("items_descartados", [])
            lineas += [
                f"### Ronda {n}",
                f"",
                f"> **Ítems confirmados:** {confirmados}  ",
                f"> **Ítems descartados:** {descartados}",
                f"",
                f"**Argumento del Auditor:**",
                f"",
                entrada.get("argumento_auditor", "_(sin argumento)_"),
                f"",
                f"**Respuesta del Metodólogo:**",
                f"",
                entrada.get("respuesta_metodologico", "_(sin respuesta)_"),
                f"",
                f"---",
                f"",
            ]

    consenso = state.get("resultado_consenso", "")
    disenso  = state.get("resultado_disenso", "")
    if consenso or disenso:
        lineas += [
            f"## Consenso y Disenso",
            f"",
            f"**Consenso:**  ",
            consenso or "_(No generado)_",
            f"",
            f"**Disenso:**  ",
            disenso or "_(No generado)_",
            f"",
        ]

    ruta.write_text("\n".join(lineas), encoding="utf-8")



def _guardar_debate_como_embeddings(
    debate_memory: list,
    historial: list,
    run_id: str,
    universidad: str,
    programa: str,
    seccion: str,
) -> None:
    """
    Vectoriza cada entrada de debate_memory y la guarda en ChromaDB persistente.

    Colección: "debate_history" (PersistentClient en ./chroma_db/debate_history/)
    Cada documento = una perspectiva del panel (subagente + contenido)
    Metadata incluye el campo "subagente" para identificar la perspectiva.

    Si debate_memory está vacío, intenta vectorizar el historial en formato antiguo.
    """
    fuentes = []
    if debate_memory:
        for item in debate_memory:
            if isinstance(item, dict) and item.get("contenido"):
                fuentes.append({
                    "texto":    item["contenido"],
                    "subagente": item.get("subagente", "desconocido"),
                    "ronda":    0,
                })
    elif historial:
        for entrada in historial:
            if not isinstance(entrada, dict):
                continue
            if entrada.get("tipo") == "panel":
                for item in entrada.get("panel", []):
                    if item.get("contenido"):
                        fuentes.append({
                            "texto":    item["contenido"],
                            "subagente": item.get("subagente", "desconocido"),
                            "ronda":    0,
                        })
            else:
                n = entrada.get("ronda", 0)
                if entrada.get("argumento_auditor"):
                    fuentes.append({
                        "texto":    entrada["argumento_auditor"],
                        "subagente": "auditor",
                        "ronda":    n,
                    })
                if entrada.get("respuesta_metodologico"):
                    fuentes.append({
                        "texto":    entrada["respuesta_metodologico"],
                        "subagente": "metodologo",
                        "ronda":    n,
                    })

    if not fuentes:
        return

    try:
        import chromadb
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        from langchain_core.documents import Document

        os.makedirs(_DEBATE_CHROMA_PATH, exist_ok=True)
        cliente  = chromadb.PersistentClient(path=_DEBATE_CHROMA_PATH)
        embed_fn = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        vs = Chroma(
            client=cliente,
            collection_name=_DEBATE_COLLECTION,
            embedding_function=embed_fn,
        )

        documentos = []
        ids        = []
        for i, fuente in enumerate(fuentes):
            documentos.append(Document(
                page_content=fuente["texto"],
                metadata={
                    "run_id":      run_id,
                    "subagente":   fuente["subagente"],
                    "ronda":       fuente["ronda"],
                    "universidad": universidad,
                    "programa":    programa,
                    "seccion":     seccion,
                },
            ))
            ids.append(f"{run_id}_{fuente['subagente']}_{i}")

        if documentos:
            vs.add_documents(documentos, ids=ids)
            logger.info(
                f"[Exportador] Debate vectorizado: {len(documentos)} entradas "
                f"en '{_DEBATE_CHROMA_PATH}'"
            )

    except ImportError as exc:
        logger.warning(f"[Exportador] No se pudo vectorizar debate (librería faltante): {exc}")
    except Exception as exc:
        logger.warning(f"[Exportador] Error vectorizando debate: {exc}")
