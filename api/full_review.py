"""
Revisión completa del proyecto en 3 fases — cobertura total, sin quemar tokens.

Fase 1 (barrido por sección):  evalúa TODAS las secciones del proyecto. Cada una
                               se diagnostica con su contenido COMPLETO (ventaneo
                               si es muy larga) contra SUS ítems de rúbrica. Nada
                               se trunca ni se queda sin leer.
Fase 2 (profundización):       la red multiagente completa corre sobre las 3
                               secciones más débiles, con 1 iteración cada una.
Fase 3 (síntesis):             arma el mapa global de mejora a partir del
                               diagnóstico de TODAS las secciones.

El informe final contiene el mapa de puntos débiles de todo el proyecto + texto
de mejora de lo más débil, nunca la tesis completa reescrita.

Por qué por sección y no por capítulo:
  El barrido por capítulo truncaba a 5000 chars/capítulo, dejando ciega la
  segunda mitad de los capítulos largos (Marco teórico, Metodología) y marcando
  como faltantes secciones que solo estaban más abajo. Diagnosticar por unidad de
  rúbrica, con todo su contenido, garantiza que el proyecto se evalúe entero.
"""

import uuid
import logging
import threading
from typing import Iterator

from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import (
    RUBRICA_ITEMS_UPAO,
    _buscar_items_seccion,
    _seccion_rubrica_para,
)
from .llm import llm_rapido, extraer_json
from .grafo import ejecutar_seccion

logger = logging.getLogger(__name__)

_MAX_CHARS_VENTANA       = 7000   # presupuesto por llamada de diagnóstico
_N_SECCIONES_PROFUNDIZAR = 3
_MIN_CHARS_UNIDAD        = 120    # por debajo: prácticamente solo título → no se diagnostica

_PROMPT_BARRIDO = """Eres un auditor académico experto en proyectos de tesis.
Evalúa el texto de UNA sección contra los criterios de rúbrica dados. Sé crítico y concreto.
Responde SOLO con JSON válido:
{{"puntaje": <0-10>, "debilidades": ["frase corta y accionable", ...]}}
Máximo 3 debilidades. Si la sección está sólida, lista 1 mejora menor (o deja la lista vacía).

Reglas:
- Evalúa SOLO lo que el texto dice. No asumas que falta algo solo porque no aparece aquí:
  puede vivir en otra sección del proyecto. Juzga el cumplimiento de los criterios sobre
  el contenido presente, no la ausencia de contenido que corresponde a otra parte.
- Revisa TODO el texto entregado antes de concluir.

CRITERIOS DE LA RÚBRICA APLICABLES:
{criterios}

SECCIÓN EVALUADA: {seccion}
{nota_ventana}
"""

_PROMPT_SINTESIS = """Eres el mentor académico principal. Con los diagnósticos por sección
de un proyecto de tesis, redacta un informe ejecutivo en markdown y español con:
1. "## Diagnóstico general" — 3-4 frases sobre el estado global del proyecto.
2. "## Mapa de puntos débiles" — lista por sección, de lo más urgente a lo menos.
3. "## Plan de acción recomendado" — 4-6 pasos concretos y priorizados.
NO reescribas la tesis. NO inventes contenido que no esté en los diagnósticos.
Máximo ~450 palabras."""


_CRITERIOS_GENERICOS_TXT = (
    "- Claridad, coherencia y registro académico del texto.\n"
    "- Rigor metodológico y consistencia con el resto del proyecto."
)


def _criterios_para_unidad(unidad: str, secciones_raw: list[str], rubrica: dict | None = None) -> str:
    """Ítems de rúbrica aplicables a la unidad. Usa la rúbrica subida si existe."""
    if rubrica:
        from backend.rag.rubric_parser import items_para_seccion
        items = items_para_seccion(rubrica, unidad)
        if not items:
            for s in secciones_raw:
                items = items_para_seccion(rubrica, s)
                if items:
                    break
        if not items:
            return _CRITERIOS_GENERICOS_TXT
        return "\n".join(f"{it['numero']:02d}. {it.get('descripcion', '')}" for it in items)

    nums = _buscar_items_seccion(unidad)
    if not nums:
        for s in secciones_raw:
            nums = _buscar_items_seccion(s)
            if nums:
                break
    if not nums:
        return _CRITERIOS_GENERICOS_TXT
    return "\n".join(f"{n:02d}. {RUBRICA_ITEMS_UPAO[n]}" for n in nums)


def _contenido_por_unidad_rubrica(doc) -> list[dict]:
    """
    Agrupa TODOS los chunks del vector store por UNIDAD DE RÚBRICA, en orden de
    lectura. '1.2.1' y '1.2.2' caen en '1.2 Objetivos…'; '4.1','4.2','4.3' caen en
    '4.1–4.3 Tipo, Método y Diseño'. Cada unidad conserva todos sus chunks (sin
    truncar) para que el diagnóstico lea la sección completa.
    """
    result = doc.vector_store._collection.get(include=["metadatas", "documents"])
    metadatas = result.get("metadatas") or []
    documents = result.get("documents") or []

    pares = sorted(
        zip(metadatas, documents),
        key=lambda md: (md[0] or {}).get("chunk_index", 0),
    )

    unidades: dict[str, dict] = {}
    for meta, texto in pares:
        seccion_raw = (meta or {}).get("seccion", "Documento")
        clave = _seccion_rubrica_para(seccion_raw) or seccion_raw
        u = unidades.setdefault(clave, {
            "unidad":        clave,
            "secciones_raw": [],
            "chunks":        [],
            "orden":         (meta or {}).get("chunk_index", 0),
        })
        if seccion_raw not in u["secciones_raw"]:
            u["secciones_raw"].append(seccion_raw)
        u["chunks"].append(texto)

    return sorted(unidades.values(), key=lambda u: u["orden"])


def _ventanas(chunks: list[str], max_chars: int = _MAX_CHARS_VENTANA) -> list[str]:
    """Parte los chunks de una sección en ventanas de ≤ max_chars, en orden de lectura."""
    ventanas: list[str] = []
    actual = ""
    for c in chunks:
        if actual and len(actual) + len(c) > max_chars:
            ventanas.append(actual.strip())
            actual = ""
        actual += c + "\n\n"
        while len(actual) > max_chars:  # chunk individual gigante (raro)
            ventanas.append(actual[:max_chars].strip())
            actual = actual[max_chars:]
    if actual.strip():
        ventanas.append(actual.strip())
    return ventanas or [""]


def _diagnosticar_unidad(llm, u: dict, rubrica: dict | None = None) -> dict:
    """Diagnostica una unidad completa (con ventaneo si excede el presupuesto)."""
    criterios = _criterios_para_unidad(u["unidad"], u["secciones_raw"], rubrica)
    ventanas  = _ventanas(u["chunks"])

    puntajes: list[int] = []
    debilidades: list[str] = []
    for i, vent in enumerate(ventanas):
        if len(vent.strip()) < _MIN_CHARS_UNIDAD and len(ventanas) > 1:
            continue
        nota = "" if len(ventanas) == 1 else f"(Parte {i + 1} de {len(ventanas)} de esta sección.)"
        try:
            resp = llm.invoke([
                SystemMessage(content=_PROMPT_BARRIDO.format(
                    criterios=criterios, seccion=u["unidad"], nota_ventana=nota,
                )),
                HumanMessage(content=vent),
            ])
            data = extraer_json(resp.content)
        except Exception as exc:
            logger.warning(f"[revision_completa] Barrido falló en '{u['unidad']}' (ventana {i + 1}): {exc}")
            data = {}

        if data.get("puntaje") is not None:
            try:
                puntajes.append(max(0, min(10, int(data["puntaje"]))))
            except (TypeError, ValueError):
                pass
        for d in (data.get("debilidades") or []):
            if d and d not in debilidades:
                debilidades.append(d)

    puntaje = round(sum(puntajes) / len(puntajes)) if puntajes else 5
    return {
        "unidad":        u["unidad"],
        "secciones_raw": u["secciones_raw"],
        "puntaje":       puntaje,
        "debilidades":   debilidades[:3],
    }


def ejecutar_revision_completa(
    doc,
    max_iteraciones: int,
    cancelar: threading.Event,
) -> Iterator[dict]:
    """Generador de eventos SSE para la revisión completa del proyecto."""
    llm = llm_rapido(temperatura=0.1)

    yield {"tipo": "fase", "fase": "barrido",
           "detalle": "Fase 1/3 — Barrido por secciones (cobertura total)…"}

    unidades = _contenido_por_unidad_rubrica(doc)
    diagnosticos: list[dict] = []

    for u in unidades:
        if cancelar.is_set():
            yield {"tipo": "cancelado"}
            return
        if sum(len(c) for c in u["chunks"]) < _MIN_CHARS_UNIDAD:
            continue

        yield {"tipo": "progreso", "detalle": f"Analizando «{u['unidad']}»…"}

        diag = _diagnosticar_unidad(llm, u, doc.rubrica)
        diagnosticos.append(diag)
        yield {"tipo": "diagnostico", "capitulo": diag["unidad"],
               "puntaje": diag["puntaje"], "debilidades": diag["debilidades"]}

    if not diagnosticos:
        yield {"tipo": "error", "detalle": "No se pudo extraer contenido evaluable del documento."}
        return

    peores = sorted(diagnosticos, key=lambda d: d["puntaje"])[:_N_SECCIONES_PROFUNDIZAR]
    resumenes: list[dict] = []

    for diag in peores:
        if cancelar.is_set():
            yield {"tipo": "cancelado"}
            return

        # Nombre real del TOC para que ejecutar_seccion tenga su propio RAG.
        seccion = next(
            (s for s in diag["secciones_raw"] if s in (doc.estructura_toc or {})),
            None,
        )
        if not seccion:
            seccion = diag["secciones_raw"][0] if diag["secciones_raw"] else diag["unidad"]

        yield {"tipo": "fase", "fase": "profundizacion",
               "detalle": f"Fase 2/3 — Red multiagente profundizando en «{seccion}» (de las más débiles)…"}

        thread_id = str(uuid.uuid4())
        for evento in ejecutar_seccion(doc, seccion, max_iteraciones=1,
                                       thread_id=thread_id, cancelar=cancelar):
            if evento["tipo"] == "seccion_completada":
                if not evento["resumen"].get("vacia"):
                    resumenes.append(evento["resumen"])
                    from . import mejoras
                    mejoras.registrar_resultado(doc, evento["resumen"]["seccion"], evento["resumen"])
            elif evento["tipo"] == "cancelado":
                yield evento
                return
            else:
                yield evento

    yield {"tipo": "fase", "fase": "sintesis", "detalle": "Fase 3/3 — Sintetizando informe global…"}

    diag_txt = "\n\n".join(
        f"{d['unidad']} — puntaje {d['puntaje']}/10\n" + "\n".join(f"- {w}" for w in d["debilidades"])
        for d in diagnosticos
    )
    try:
        sintesis = llm.invoke([
            SystemMessage(content=_PROMPT_SINTESIS),
            HumanMessage(content=diag_txt),
        ]).content
    except Exception as exc:
        logger.warning(f"[revision_completa] Síntesis falló: {exc}")
        sintesis = "## Diagnóstico general\n\n" + diag_txt

    partes = [sintesis, "\n---\n", "# Mejoras propuestas para las secciones más débiles\n"]
    for r in resumenes:
        badge = ""
        if r.get("puntaje") is not None and r.get("puntaje_max"):
            badge = f" — **{r['puntaje']}/{r['puntaje_max']} pts**"
        partes.append(f"## {r['seccion']}{badge}\n")
        if r.get("puntos_debiles"):
            partes.extend(f"- {p}" for p in r["puntos_debiles"])
            partes.append("")
        if r.get("texto_mejorado"):
            partes.append(f"**Propuesta de texto mejorado:**\n\n{r['texto_mejorado']}\n")

    informe = "\n".join(partes).strip()
    yield {"tipo": "resultado", "informe_md": informe,
           "detalles": [r["detalle"] for r in resumenes if r.get("detalle")],
           "resumen": {"diagnosticos": diagnosticos,
                       "profundizadas": [r["seccion"] for r in resumenes]}}
