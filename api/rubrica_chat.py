"""
Lineamientos de rúbrica para la capa de chat (conversador + debate rápido).

Mapea la consulta del estudiante a la sección de su proyecto, saca los ítems de
la rúbrica que la gobiernan y arma un bloque de texto con los criterios + la guía
para alcanzar el puntaje máximo. Reutilizado por el conversador y por el
sintetizador del mini-grafo de debate.

No evalúa ni califica: solo expone los criterios para ORIENTAR al estudiante.
"""

import logging
import re

from backend.rag.rubric_parser import items_para_seccion, escala_max_rubrica

logger = logging.getLogger(__name__)

_MAX_ITEMS_GENERAL = 12

# Verbos/coletillas iniciales a quitar para que la resolución vea el CONCEPTO, no
# "corrige mi …" (que arrastra el embedding a una sección equivocada).
_RE_LIMPIAR = re.compile(
    r"^\s*(por favor[,\s]*)?(puedes?\s+|me\s+|ay[úu]dame\s+a\s+|quiero\s+que\s+|c[óo]mo\s+|"
    r"corrig\w*|corrije|mejor\w*|revis\w*|redact\w*|reformul\w*|reescrib\w*|eval[úu]\w*|"
    r"calific\w*|analiz\w*|dame|da\s+|gener\w*|haz\w*|pul\w*)\s*", re.I,
)

# Conceptos del NÚCLEO (sujeto) → para corregir cuando la semántica falla.
_CONCEPTOS = [
    ("titulo",    re.compile(r"t[íi]tulo", re.I)),
    ("problema",  re.compile(r"(problema|planteamiento|formulaci[óo]n|pregunta)", re.I)),
    ("objetivo",  re.compile(r"objetivo", re.I)),
    ("hipotesis", re.compile(r"(hip[óo]tesis|\bsupuesto)", re.I)),
    ("variable",  re.compile(r"(variable|operacionaliz|matriz de (consistencia|coherencia))", re.I)),
]


def _limpiar_consulta(consulta: str) -> str:
    c = (consulta or "").strip()
    c2 = _RE_LIMPIAR.sub("", c)
    c2 = re.sub(r"^\s*(mis?|el|la|los|las|un|una|de)\s+", "", c2, flags=re.I)
    return c2.strip() or c


def _concepto_de(texto: str) -> str | None:
    """Concepto del núcleo que aparece PRIMERO en el texto (o None)."""
    pos_min, concepto = None, None
    for nombre, pat in _CONCEPTOS:
        m = pat.search(texto or "")
        if m and (pos_min is None or m.start() < pos_min):
            pos_min, concepto = m.start(), nombre
    return concepto


def _es_capitulo(nombre: str) -> bool:
    """Encabezado de capítulo (prefijo de un solo nivel: '1', '2'…): trae el capítulo
    ENTERO y desenfoca la mejora. Se prefiere una subsección específica."""
    from backend.config import _prefijo_num
    p = _prefijo_num(nombre)
    return bool(p) and "." not in p


def resolver_seccion_consulta(doc, consulta: str) -> str | None:
    """Mapea la consulta a una sección del TOC, robusto a verbos y a fallos semánticos.

    1) Limpia la consulta (quita «corrige mi …»). 2) Resuelve por semántica. 3) CORRIGE:
    si la consulta nombra un concepto del núcleo (problema/objetivos/título/hipótesis/
    variables) y la sección semántica es de OTRO concepto, prefiere una sección del
    concepto correcto. Así «corrige mi planteamiento» no termina en «3.2 Variables».
    """
    if doc is None:
        return None
    toc = list((getattr(doc, "estructura_toc", None) or {}).keys())
    if not toc:
        return None

    q = _limpiar_consulta(consulta)
    seccion = None
    if getattr(doc, "vector_store", None) is not None:
        from backend.rag import resolver_seccion_semantica
        try:
            seccion = resolver_seccion_semantica(doc.vector_store, q, toc)
        except Exception as exc:
            logger.warning(f"[rubrica_chat] No se pudo resolver la sección: {exc}")

    concepto = _concepto_de(q)
    # Corrige si la semántica falló (otro concepto), O si cayó en un encabezado de capítulo.
    if concepto and (seccion is None or _concepto_de(seccion) != concepto or _es_capitulo(seccion)):
        candidatos = [n for n in toc if _concepto_de(n) == concepto]
        # Prefiere subsecciones específicas sobre encabezados de capítulo ('1.', '2.').
        especificas = [n for n in candidatos if not _es_capitulo(n)]
        sec_c = next(iter(especificas or candidatos), None)
        if sec_c and sec_c != seccion:
            logger.info(f"[rubrica_chat] Corrección por concepto «{concepto}»: '{seccion}' → '{sec_c}'")
            seccion = sec_c
    return seccion


def criterios_relevantes(doc, consulta: str, seccion_hint: str | None = None) -> tuple[str, str | None]:
    """Devuelve `(bloque_md, seccion_detectada)`.

    `bloque_md`: criterios de la rúbrica relevantes a la consulta + cómo llegar al
    máximo puntaje (cadena vacía si el doc no tiene rúbrica). `seccion_detectada`:
    la sección del TOC a la que se mapeó la consulta (o None) — SIEMPRE se resuelve
    (aunque no haya rúbrica), para que el mini-debate ancle el contexto correcto.
    """
    seccion = seccion_hint or resolver_seccion_consulta(doc, consulta)

    rubrica = getattr(doc, "rubrica", None) if doc else None
    if not rubrica or not rubrica.get("items"):
        return "", seccion

    items = items_para_seccion(rubrica, seccion) if seccion else []
    if items:
        fuente = f"de la sección «{seccion}»"
    else:
        # Sin mapeo claro: usar los primeros ítems de la rúbrica como guía general.
        items = list(rubrica.get("items", []))[:_MAX_ITEMS_GENERAL]
        fuente = "de tu rúbrica"

    if not items:
        return "", seccion

    esc = escala_max_rubrica(rubrica)
    lineas = [f"- Ítem {it.get('numero', '?')}: {it.get('descripcion', '')}" for it in items]
    bloque = (
        f"CRITERIOS DE LA RÚBRICA RELEVANTES {fuente} "
        f"(cada uno se califica de 0 a {esc}; el máximo exige cumplirlos por completo):\n"
        + "\n".join(lineas)
    )
    return bloque, seccion
