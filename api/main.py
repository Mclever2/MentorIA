"""
API FastAPI — backend del frontend React (Cloud Run).

Endpoints:
  GET  /health                      — health check
  GET  /api/biblioteca              — libros indexados en la memoria RAG
  POST /api/documentos              — sube PDF de tesis, vectoriza, devuelve estructura
  POST /api/documentos/{id}/rubrica — sube rúbrica PDF opcional
  POST /api/chat                    — interpreta el mensaje; responde o crea un run
  GET  /api/runs/{id}/stream        — SSE con el progreso de los agentes
  POST /api/runs/{id}/cancelar      — botón de detener a los agentes
  POST /evaluar                     — endpoint legacy (compatibilidad)
"""

import os
import json
import uuid
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .auth import usuario_actual
from . import registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("PRELOAD_ON_STARTUP", "1") == "1":
        try:
            from .deps import precalentar
            precalentar()
        except Exception:
            logger.exception("[startup] Falló el precalentamiento (continuará lazy)")
    yield


app = FastAPI(
    title="MentorIA — API multiagente de mentoría de tesis",
    version="2.0.0",
    lifespan=lifespan,
)

_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/biblioteca")
def biblioteca(_user: dict = Depends(usuario_actual)):
    from backend.rag import listar_libros
    from .deps import get_biblioteca

    libros = listar_libros(get_biblioteca())
    return {"libros": libros, "total_fragmentos": sum(l["fragmentos"] for l in libros)}



@app.post("/api/documentos")
async def subir_documento(
    archivo: UploadFile = File(...),
    memoria: str = Form(default=""),
    rubrica: str = Form(default=""),
    perfil_universidad: str = Form(default=""),
    user: dict = Depends(usuario_actual),
):
    """
    Extrae texto del PDF (omitiendo el índice), vectoriza y devuelve la estructura.

    `memoria` (JSON opcional) llega en la rehidratación de un chat: reconstruye
    las secciones evaluadas y reaplica el texto corregido a la memoria RAG.
    `rubrica` y `perfil_universidad` (JSON opcionales) son el snapshot de la
    sesión: la rúbrica ya parseada/mapeada y el perfil de universidad destilado,
    para que el doc quede listo sin re-procesar.
    """
    import json as _json

    from backend.rag import (
        construir_vector_store,
        extraer_contenido_sin_indice,
        obtener_stats_secciones,
    )
    from .deps import get_embeddings
    from . import mejoras

    contenido = await archivo.read()
    pdf_hash = hashlib.md5(contenido).hexdigest()
    user_id = user.get("sub", "anon")

    memoria_dict = {}
    if memoria:
        try:
            memoria_dict = _json.loads(memoria)
        except Exception:
            logger.warning("[documentos] memoria malformada, se ignora")

    rubrica_dict = _parse_json_form(rubrica, "rubrica")
    perfil_dict = _parse_json_form(perfil_universidad, "perfil_universidad")

    existente = registry.buscar_documento_por_hash(user_id, pdf_hash)
    if existente:
        # Ya está en memoria del proceso (mismo instante): conserva su estado,
        # pero refresca el snapshot de rúbrica/perfil por si cambió en la sesión.
        _aplicar_recursos_sesion(existente, rubrica_dict, perfil_dict)
        return _documento_a_json(existente, ya_indexado=True)

    try:
        paginas, estructura_toc = extraer_contenido_sin_indice(contenido)
        total_chars = sum(len(t) for _, t in paginas)
        if total_chars < 100:
            raise ValueError(
                "El PDF parece vacío o es un escaneo sin texto seleccionable. "
                "Asegúrate de que el PDF sea nativo (no solo imágenes)."
            )

        vector_store = construir_vector_store(
            paginas, estructura_toc, get_embeddings(),
            collection_name=f"tesis_{pdf_hash[:8]}_{uuid.uuid4().hex[:6]}",
        )
        stats = obtener_stats_secciones(vector_store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("[documentos] Error vectorizando")
        raise HTTPException(status_code=500, detail=f"Error procesando el PDF: {exc}")

    doc = registry.registrar_documento(
        user_id=user_id,
        nombre=archivo.filename or "tesis.pdf",
        pdf_hash=pdf_hash,
        vector_store=vector_store,
        estructura_toc=estructura_toc or {},
        stats=stats,
    )

    _aplicar_recursos_sesion(doc, rubrica_dict, perfil_dict)

    if memoria_dict:
        mejoras.restaurar_memoria(doc, memoria_dict)

    logger.info(f"[documentos] '{doc.nombre}' indexado — {len(stats)} secciones")
    return _documento_a_json(doc)


def _parse_json_form(valor: str, etiqueta: str) -> dict:
    """Parsea un campo de formulario JSON; devuelve {} si está vacío o malformado."""
    import json as _json
    if not valor:
        return {}
    try:
        data = _json.loads(valor)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning(f"[documentos] {etiqueta} malformado, se ignora")
        return {}


def _aplicar_recursos_sesion(doc, rubrica_dict: dict, perfil_dict: dict) -> None:
    """Adjunta al documento el snapshot de rúbrica y perfil de universidad de la sesión.

    Si la rúbrica llegó sin `mapa_secciones` (se subió antes que el proyecto), se
    mapea ahora contra el TOC real del documento.
    """
    if rubrica_dict and rubrica_dict.get("items"):
        doc.rubrica = rubrica_dict
        doc.rubrica_nombre = rubrica_dict.get("nombre") or doc.rubrica_nombre

    # Re-mapear la rúbrica al TOC de ESTE proyecto. El mapa se persiste en el
    # snapshot, así que una rúbrica reutilizada en otro proyecto traería un mapa
    # obsoleto: se recalcula si la firma del TOC no coincide (proyecto distinto).
    if doc.rubrica and doc.rubrica.get("items") and doc.estructura_toc:
        try:
            from .rubrica_service import mapear_rubrica, _firma_toc, _toc_nombres
            firma_actual = _firma_toc(_toc_nombres(doc.estructura_toc))
            if doc.rubrica.get("mapa_toc_firma") != firma_actual:
                mapear_rubrica(doc.rubrica, doc.estructura_toc)
                logger.info("[documentos] Rúbrica (re)mapeada al TOC de este proyecto.")
        except Exception:
            logger.exception("[documentos] No se pudo mapear la rúbrica al TOC")

    if perfil_dict:
        doc.universidad = perfil_dict.get("universidad") or doc.universidad
        doc.programa = perfil_dict.get("programa") or doc.programa
        ctx = perfil_dict.get("contexto_institucional") or ""
        enf = perfil_dict.get("enfasis") or ""
        doc.perfil_institucional = (ctx + ("\n\n" + enf if enf else "")).strip() or doc.perfil_institucional


def _documento_a_json(doc, ya_indexado: bool = False) -> dict:
    return {
        "doc_id":         doc.doc_id,
        "nombre":         doc.nombre,
        "hash":           doc.pdf_hash,
        "ya_indexado":    ya_indexado,
        "estructura_toc": doc.estructura_toc,
        "stats":          doc.stats,
        "rubrica":        (
            {"nombre": doc.rubrica_nombre,
             "total_items": doc.rubrica.get("total_items"),
             "puntaje_maximo": doc.rubrica.get("puntaje_maximo")}
            if doc.rubrica else None
        ),
        # Rúbrica completa (incluye mapa_secciones ya calculado) para que el
        # frontend re-persista el snapshot mapeado tras indexar el proyecto.
        "rubrica_full":   doc.rubrica if doc.rubrica else None,
    }


@app.post("/api/documentos/{doc_id}/rubrica")
async def subir_rubrica(
    doc_id: str,
    archivo: UploadFile = File(...),
    user: dict = Depends(usuario_actual),
):
    """Parsea, valida y mapea la rúbrica a las secciones del proyecto.

    Devuelve la rúbrica completa (incluido `mapa_secciones`) para que el frontend
    la persista como snapshot de la sesión y default del usuario.
    """
    from .rubrica_service import procesar_rubrica, RubricaInvalida

    doc = _obtener_doc_o_404(doc_id, user)
    contenido = await archivo.read()
    try:
        rubrica = procesar_rubrica(contenido, doc.estructura_toc)
    except RubricaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("[rubrica] Error procesando")
        raise HTTPException(status_code=500, detail=f"Error procesando la rúbrica: {exc}")

    rubrica["nombre"] = archivo.filename or "rúbrica.pdf"
    doc.rubrica = rubrica
    doc.rubrica_nombre = rubrica["nombre"]

    secciones_mapeadas = sum(1 for v in (rubrica.get("mapa_secciones") or {}).values() if v)
    return {
        "rubrica": rubrica,
        "nombre": rubrica["nombre"],
        "total_items": rubrica["total_items"],
        "secciones": len(rubrica.get("secciones", {})),
        "secciones_mapeadas": secciones_mapeadas,
        "items_ausentes": len(rubrica.get("items_ausentes") or []),
        "puntaje_maximo": rubrica["puntaje_maximo"],
    }


def _obtener_doc_o_404(doc_id: str, user: dict):
    doc = registry.obtener_documento(doc_id)
    if doc is None or doc.user_id != user.get("sub", "anon"):
        raise HTTPException(
            status_code=404,
            detail="Documento no disponible en el servidor (puede haberse reiniciado). "
                   "Vuelve a subir tu PDF para continuar.",
        )
    return doc


class BuscarUniversidadRequest(BaseModel):
    universidad: str
    programa: str = "ingeniería de sistemas"
    nivel: str = "tesis"


@app.post("/api/universidad/buscar")
def buscar_universidad(req: BuscarUniversidadRequest, _user: dict = Depends(usuario_actual)):
    """Busca reglamentos de la universidad (Tavily) y destila un perfil.

    Si no encuentra material útil, devuelve {encontrado: false} para que el
    frontend ofrezca subir el reglamento manualmente.
    """
    from .reglamento_service import perfil_desde_busqueda

    universidad = (req.universidad or "").strip()
    if not universidad:
        raise HTTPException(status_code=422, detail="Indica el nombre de la universidad.")

    try:
        res = perfil_desde_busqueda(universidad, req.programa, req.nivel)
    except Exception as exc:
        logger.exception("[universidad] Error en búsqueda")
        raise HTTPException(status_code=500, detail=f"Error buscando reglamentos: {exc}")

    if not res.get("ok"):
        return {"encontrado": False, "motivo": res.get("motivo")}
    return {"encontrado": True, "perfil": res["perfil"]}


@app.post("/api/universidad/subir")
async def subir_reglamento(
    archivo: UploadFile = File(...),
    universidad: str = Form(...),
    programa: str = Form(default="ingeniería de sistemas"),
    nivel: str = Form(default="tesis"),
    _user: dict = Depends(usuario_actual),
):
    """Destila el perfil institucional desde un reglamento subido (PDF/.docx)."""
    from .reglamento_service import perfil_desde_documento, ReglamentoInvalido

    contenido = await archivo.read()
    try:
        perfil = perfil_desde_documento(
            archivo.filename or "reglamento.pdf", contenido,
            (universidad or "").strip(), programa, nivel,
        )
    except ReglamentoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("[universidad] Error procesando reglamento")
        raise HTTPException(status_code=500, detail=f"Error procesando el reglamento: {exc}")

    return {"perfil": perfil}


class RecursosRequest(BaseModel):
    rubrica: dict | None = None
    perfil_universidad: dict | None = None
    limpiar_rubrica: bool = False
    limpiar_perfil: bool = False


@app.post("/api/documentos/{doc_id}/recursos")
def set_recursos(doc_id: str, req: RecursosRequest, user: dict = Depends(usuario_actual)):
    """Sincroniza rúbrica/perfil en el documento vivo cuando cambian desde el navbar.

    Evita re-indexar el PDF: solo actualiza lo que los agentes usarán en el próximo run.
    """
    doc = _obtener_doc_o_404(doc_id, user)
    if req.limpiar_rubrica:
        doc.rubrica = None
        doc.rubrica_nombre = None
    if req.limpiar_perfil:
        doc.universidad = None
        doc.programa = None
        doc.perfil_institucional = None
    _aplicar_recursos_sesion(doc, req.rubrica or {}, req.perfil_universidad or {})
    return {"ok": True}



class TurnoChat(BaseModel):
    rol: str
    contenido: str


class ChatRequest(BaseModel):
    mensaje: str
    doc_id: str | None = None
    max_iteraciones: int = 2
    contexto_previo: str = ""
    historial: list[TurnoChat] = []
    confirmar_reevaluacion: bool = False
    decision_mejoras: str | None = None


@app.post("/api/chat")
def chat(req: ChatRequest, user: dict = Depends(usuario_actual)):
    from .intent import interpretar_mensaje
    from . import mejoras

    doc = registry.obtener_documento(req.doc_id) if req.doc_id else None
    if doc is not None and doc.user_id != user.get("sub", "anon"):
        doc = None

    toc_nombres = sorted(
        (doc.estructura_toc or {}).items(), key=lambda x: x[1]
    ) if doc else []
    toc_nombres = [n for n, _ in toc_nombres]

    historial = [t.model_dump() for t in req.historial]

    intencion = interpretar_mensaje(
        mensaje=req.mensaje,
        toc_nombres=toc_nombres,
        contexto_previo=req.contexto_previo,
        hay_documento=doc is not None,
        historial=historial,
        vector_store=doc.vector_store if doc else None,
    )

    if intencion["modo"] == "conversacion":
        from .conversador import responder_consulta
        from .deps import get_biblioteca

        respuesta = responder_consulta(
            mensaje=req.mensaje,
            historial=historial,
            doc=doc,
            biblioteca=get_biblioteca(),
        )
        return {"tipo": "conversacion", "respuesta": respuesta}

    objetivo = intencion["secciones"] if intencion["modo"] == "secciones" else []

    ya_evaluadas = [s for s in objetivo if s in doc.evaluadas]
    if ya_evaluadas and not req.confirmar_reevaluacion:
        lista = ", ".join(f"**{s}**" for s in ya_evaluadas)
        return {
            "tipo": "confirmacion",
            "subtipo": "reevaluar",
            "secciones": ya_evaluadas,
            "mensaje": (
                f"La sección {lista} ya fue evaluada en esta asesoría. "
                "¿Quieres que la red de agentes la revise de nuevo?"
            ),
        }

    pend = mejoras.pendientes(doc)
    pend_otras = [s for s in pend if s not in objetivo]
    if pend_otras and req.decision_mejoras is None:
        lista = ", ".join(f"**{s}**" for s in pend_otras)
        return {
            "tipo": "confirmacion",
            "subtipo": "aplicar_mejoras",
            "secciones": pend_otras,
            "mensaje": (
                f"Tengo texto corregido de {lista} que aún no incorporé a mi memoria. "
                "¿Lo uso en lugar del texto original de tu PDF para esta revisión? "
                "(Tu PDF no se modifica — solo lo que yo recuerdo del proyecto. "
                "Se incorpora únicamente el texto corregido, no las sugerencias.)"
            ),
        }

    aplicadas: list[str] = []
    if req.decision_mejoras == "aplicar" and pend:
        aplicadas = mejoras.aplicar_pendientes(doc)
        logger.info(f"[chat] Mejoras incorporadas a la memoria RAG: {aplicadas}")

    max_iter = max(1, min(3, req.max_iteraciones))
    # La revisión COMPLETA siempre profundiza con 1 iteración (ahorro de tokens):
    # califica todos los ítems con el barrido barato y solo profundiza lo más débil.
    if intencion["modo"] == "completo":
        max_iter = 1
    run = registry.registrar_run(
        user_id=user.get("sub", "anon"),
        doc_id=doc.doc_id,
        modo=intencion["modo"],
        secciones=intencion["secciones"],
        max_iteraciones=max_iter,
    )
    return {
        "tipo": "run",
        "run_id": run.run_id,
        "modo": run.modo,
        "secciones": run.secciones,
        "max_iteraciones": max_iter,
        "mejoras_aplicadas": aplicadas,
    }



def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


def _eventos_run(run, doc):
    """Generador síncrono: ejecuta el run y emite eventos (corre en threadpool)."""
    from .grafo import ejecutar_seccion, informe_secciones_md
    from .full_review import ejecutar_revision_completa

    run.estado = "ejecutando"
    yield {"tipo": "inicio", "modo": run.modo, "secciones": run.secciones}

    adquirido = registry.RUN_EXCLUSIVO.acquire(timeout=0.1)
    if not adquirido:
        yield {"tipo": "fase", "fase": "cola", "detalle": "Esperando a que termine otra revisión…"}
        registry.RUN_EXCLUSIVO.acquire()
        adquirido = True

    try:
        if run.modo == "completo":
            ultimo = None
            for evento in ejecutar_revision_completa(doc, run.max_iteraciones, run.cancelar):
                ultimo = evento
                yield evento
            run.estado = (
                "cancelado" if (ultimo or {}).get("tipo") == "cancelado"
                else "completado"
            )
            # El chat rápido recordará esta evaluación (no pierde el hilo).
            if run.estado == "completado" and (ultimo or {}).get("resumen_chat"):
                doc.ultima_revision = ultimo["resumen_chat"]
        else:
            from . import mejoras

            resumenes: list[dict] = []
            for seccion in run.secciones:
                thread_id = str(uuid.uuid4())
                for evento in ejecutar_seccion(
                    doc, seccion, run.max_iteraciones, thread_id, run.cancelar
                ):
                    if evento["tipo"] == "seccion_completada":
                        resumen = evento["resumen"] | {"seccion": seccion}
                        resumenes.append(resumen)
                        if not resumen.get("vacia"):
                            mejoras.registrar_resultado(doc, seccion, resumen)
                    elif evento["tipo"] == "cancelado":
                        run.estado = "cancelado"
                        yield evento
                        return
                    else:
                        yield evento
                if run.cancelar.is_set():
                    run.estado = "cancelado"
                    yield {"tipo": "cancelado"}
                    return

            informe = informe_secciones_md(resumenes)
            run.estado = "completado"

            # El chat rápido recordará esta revisión por secciones.
            _partes = []
            for r in resumenes:
                if r.get("vacia"):
                    continue
                p, mx = r.get("puntaje"), r.get("puntaje_max")
                nota = f"{round(p)}/{mx}" if (p is not None and mx) else "s/n"
                deb = "; ".join((r.get("puntos_debiles") or [])[:2])
                _partes.append(f"{r.get('seccion')}: {nota}" + (f" (falta: {deb})" if deb else ""))
            if _partes:
                doc.ultima_revision = {
                    "tipo": "secciones",
                    "texto": "Última revisión por secciones — " + " · ".join(_partes) + ".",
                }

            yield {"tipo": "resultado", "informe_md": informe,
                   "detalles": [r["detalle"] for r in resumenes if r.get("detalle")],
                   "resumen_chat": doc.ultima_revision or None,
                   "resumen": {"secciones": [r.get("seccion") for r in resumenes]}}
    except Exception as exc:
        logger.exception(f"[runs] Error en run {run.run_id}")
        run.estado = "error"
        yield {"tipo": "error", "detalle": f"[{type(exc).__name__}] {exc}"}
    finally:
        if adquirido:
            registry.RUN_EXCLUSIVO.release()

    yield {"tipo": "fin", "estado": run.estado}


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str, user: dict = Depends(usuario_actual)):
    run = registry.obtener_run(run_id)
    if run is None or run.user_id != user.get("sub", "anon"):
        raise HTTPException(status_code=404, detail="Run no encontrado.")
    if run.estado != "pendiente":
        raise HTTPException(status_code=409, detail=f"Run ya está en estado '{run.estado}'.")

    doc = _obtener_doc_o_404(run.doc_id, user)

    def gen():
        for evento in _eventos_run(run, doc):
            yield _sse(evento)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/cancelar")
def cancelar_run(run_id: str, user: dict = Depends(usuario_actual)):
    run = registry.obtener_run(run_id)
    if run is None or run.user_id != user.get("sub", "anon"):
        raise HTTPException(status_code=404, detail="Run no encontrado.")
    run.cancelar.set()
    return {"ok": True, "estado": run.estado}



def _extraer_texto_pdf(contenido: bytes, seccion: str) -> str:
    import io
    import pdfplumber

    texto_completo = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                texto_completo.append(t)
    return "\n\n".join(texto_completo)


@app.post("/evaluar")
async def evaluar_tesis(
    archivo_pdf: UploadFile = File(...),
    universidad: str = Form(...),
    programa: str = Form(...),
    seccion: str = Form(..., description="Nombre de la sección a evaluar"),
    modalidad: str = Form(default="tesis"),
):
    """Versión legacy síncrona: PDF completo como contexto, sin RAG ni streaming."""
    from backend.graph.workflow import create_graph, get_run_config
    from .grafo import construir_estado_inicial

    run_id = str(uuid.uuid4())
    try:
        contenido_pdf = await archivo_pdf.read()
        texto_seccion = _extraer_texto_pdf(contenido_pdf, seccion)

        from config import Config

        estado_inicial = construir_estado_inicial(
            run_id=run_id,
            seccion=seccion,
            contexto_tesis=texto_seccion,
            contexto_dependencias="",
            contexto_teorico="",
            rubrica_dinamica=None,
            max_iteraciones=Config.MAX_ITERATIONS,
            universidad=universidad,
            programa=programa,
            modalidad=modalidad,
        )

        graph = create_graph()
        run_config = get_run_config(thread_id=run_id)
        estado_final = graph.invoke(estado_inicial, config=run_config)

        ruta_json = f"./outputs/run_{run_id}.json"
        from evaluator.evaluator import evaluar_desde_archivo
        metricas = evaluar_desde_archivo(ruta_json)

        return JSONResponse(content={
            "run_id":             run_id,
            "texto_mejorado":     estado_final.get("texto_iterado"),
            "puntaje_final":      estado_final.get("puntaje_estimado"),
            "metricas":           metricas["metricas"],
            "resultado_consenso": estado_final.get("resultado_consenso"),
        })
    except Exception as exc:
        logger.exception(f"[API] Error en run_id={run_id}")
        raise HTTPException(status_code=500, detail=str(exc))
