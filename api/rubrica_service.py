"""
Servicio de rúbrica personalizada.

Flujo al subir una rúbrica (PDF):
  1. Extraer ítems con el parser regex existente (parse_rubrica_pdf).
  2. Validar que sea realmente una rúbrica (estructural + LLM barato).
  3. Mapear cada ítem a la(s) sección(es) del proyecto donde aplica
     (precompute con LLM, una sola vez), usando el TOC del documento.

El resultado es el dict de rúbrica enriquecido con `mapa_secciones`, que viaja
como `rubrica_dinamica` en el estado del grafo y se persiste en Supabase.
Cuando una sección no tiene ítems mapeados, NO se evalúa con la rúbrica
(no se inventan errores) — coherente con lo pedido por el usuario.
"""

import json
import logging
import re
import unicodedata
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage

from backend.rag.rubric_parser import parse_rubrica_pdf
from .llm import llm_rapido, extraer_json

logger = logging.getLogger(__name__)

_MIN_ITEMS = 3


class RubricaInvalida(ValueError):
    """La rúbrica subida no es válida (vacía, sin relación o no parseable)."""


_PROMPT_VALIDACION = """Eres un validador. Recibes el texto extraído de un archivo que el \
estudiante subió como "rúbrica de evaluación de tesis/proyecto". Decide si realmente es una \
rúbrica o ficha de evaluación (criterios/ítems con los que se califica un trabajo académico).

Responde SOLO JSON: {{"es_rubrica": true|false, "motivo": "una frase breve"}}

NO es rúbrica si: está vacío, es la tesis misma, es un reglamento general, o es un documento \
sin criterios de evaluación.

TEXTO:
{texto}
"""

_PROMPT_MAPEO = """Eres un experto en evaluación de tesis. Tienes (A) los ÍTEMS de una rúbrica y \
(B) las SECCIONES reales del proyecto del estudiante, cada una con un ID entre corchetes \
(S1, S2, …). Asigna a cada sección los números de ítem de la rúbrica que aplican a esa sección \
(los que evalúan ese contenido).

Reglas:
- Usa los IDs de sección (S1, S2, …) como claves, NUNCA el texto de la sección.
- Un ítem puede aplicar a varias secciones; una sección puede tener varios ítems.
- Asigna CADA ítem a la(s) sección(es) MÁS pertinente(s), aunque el nombre no coincida \
literalmente. Razona dónde se evaluaría ese criterio en una tesis. Guíate por estos casos típicos \
(adáptalos a las secciones que existan en ESTE proyecto):
  · Ítems del TÍTULO o de la "línea de investigación": si no hay una sección de título, asígnalos \
a la sección de tipo de investigación y/o a objetivos/variables (la línea de investigación se \
alinea con el tipo de investigación).
  · Ítems sobre CITAS, paráfrasis, postura crítica frente a los autores o normas de citación \
(APA, Vancouver…): asígnalos a las secciones donde se usan fuentes (antecedentes y base/marco \
teórico); los de conformidad de referencias, también a Referencias.
  · MATRIZ DE CONSISTENCIA u operacionalización de variables: si no hay sección propia, asígnala \
a la sección de Variables.
  · ESQUEMA o gráfico del DISEÑO de investigación: asígnalo a Diseño del estudio y/o Tipo de \
investigación.
- NO dejes un ítem sin asignar si existe una sección razonablemente relacionada. Déjalo sin \
asignar SOLO si ninguna sección del proyecto trata ese aspecto.
- Los números de ítem van como enteros SIN ceros a la izquierda (escribe 4, NO 04).
- Responde SOLO JSON válido: {{"mapa": {{"S1": [4, 8, 10], "S2": [9]}}}}

(A) ÍTEMS DE LA RÚBRICA:
{items}

(B) SECCIONES DEL PROYECTO:
{secciones}
"""


def _validar_es_rubrica(texto_raw: str) -> None:
    """Validación semántica barata. Falla abierto si el LLM no responde."""
    muestra = (texto_raw or "").strip()
    if len(muestra) < 40:
        raise RubricaInvalida(
            "El archivo parece vacío o no tiene texto seleccionable. "
            "Sube la rúbrica en PDF nativo (no escaneado)."
        )
    try:
        resp = llm_rapido(temperatura=0.0).invoke([
            SystemMessage(content=_PROMPT_VALIDACION.format(texto=muestra[:3000])),
            HumanMessage(content="¿Es una rúbrica de evaluación?"),
        ])
        data = extraer_json(resp.content)
    except Exception as exc:
        logger.warning(f"[rubrica] Validación LLM no disponible ({exc}); se omite.")
        return

    if data and data.get("es_rubrica") is False:
        motivo = data.get("motivo", "no parece una rúbrica de evaluación")
        raise RubricaInvalida(
            f"El archivo no parece una rúbrica de evaluación ({motivo}). "
            "Sube la ficha/rúbrica con la que tu jurado calificará el proyecto."
        )


def _norm(texto: str) -> str:
    """Normaliza para comparar: sin acentos, sin puntuación, minúsculas."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _prefijo(texto: str) -> str:
    m = re.match(r"\s*(\d[\d.]*)", texto or "")
    return m.group(1).rstrip(".") if m else ""


def _resolver_seccion(clave: str, id_to_name: dict[str, str], toc_nombres: list[str]) -> Optional[str]:
    """Resuelve una clave devuelta por el LLM (ID 'S3', nombre, o prefijo) a un nombre de TOC."""
    clave = (clave or "").strip()
    if clave in id_to_name:                       # ID directo: "S3"
        return id_to_name[clave]
    cn = _norm(clave)
    for n in toc_nombres:                          # nombre normalizado
        if _norm(n) == cn:
            return n
    pref = _prefijo(clave)                          # prefijo numérico: "1.2.1"
    if pref:
        for n in toc_nombres:
            if _prefijo(n) == pref:
                return n
    return None


# Ítems TRANSVERSALES: se evalúan donde se usan fuentes (no en una sola sección).
# USO de citas/fuentes dentro del texto → se evalúa donde se usan (antecedentes/marco).
_RE_CITA_USO = re.compile(
    r"\b(citas?|cita textual|par[aá]frasis|postura cr[ií]tica|"
    r"normas? (internacionales?|de citaci[oó]n)|apa|vancouver|harvard|iso)\b",
    re.IGNORECASE,
)
# La LISTA de referencias → sección de Referencias.
_RE_REF_ITEM = re.compile(
    r"(referencias bibliogr|en las referencias|redacci[oó]n de las referencias|"
    r"incorporad[oa]s? todos los autores)",
    re.IGNORECASE,
)
_RE_NORMAS = re.compile(
    r"(normas? (internacionales?|de citaci[oó]n)|apa|vancouver|harvard|iso)", re.IGNORECASE
)
# Fuentes de FINANCIAMIENTO (no presupuesto): si no hay sección, el proyecto no lo cubre.
_RE_FINANC_FUENTE = re.compile(r"\b(financiamiento|fuentes?\s+de\s+financ\w*)\b", re.IGNORECASE)

_RE_SEC_TEORICO = re.compile(
    r"(antecedent|marco te[oó]ric|base te[oó]ric|marco conceptual|estado del arte)",
    re.IGNORECASE,
)
_RE_SEC_REF     = re.compile(r"referencia", re.IGNORECASE)
_RE_SEC_FINANC  = re.compile(r"(financ|presupuesto)", re.IGNORECASE)

_UMBRAL_EMB = 0.76  # similitud mínima para asignar un ítem por embeddings


def _firma_toc(toc_nombres: list[str]) -> str:
    """Huella del TOC para saber si un mapa fue calculado contra ESTE proyecto."""
    import hashlib
    base = "|".join(sorted(_norm(n) for n in toc_nombres if n))
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def _secs_que_matchean(toc_nombres: list[str], patron: re.Pattern) -> list[str]:
    return [n for n in toc_nombres if patron.search(n or "")]


def _asignar_por_embeddings(no_mapeados: list[dict], toc_nombres: list[str]) -> dict[int, str]:
    """Asigna cada ítem sin sección a la sección de nombre MÁS similar (embeddings).

    Determinístico y sin LLM. Solo asigna si la mejor similitud supera el umbral;
    así un ítem cuyo contenido no vive en ninguna sección queda fuera (→ ausente).
    """
    asignaciones: dict[int, str] = {}
    if not no_mapeados or not toc_nombres:
        return asignaciones
    try:
        import numpy as np
        from backend.rag.embeddings import cargar_modelo_embeddings
        emb = cargar_modelo_embeddings()
        sec_vecs  = np.array(emb.embed_documents(list(toc_nombres)), dtype=float)
        item_vecs = np.array(emb.embed_documents([it.get("descripcion", "") for it in no_mapeados]), dtype=float)

        def _unit(m):
            n = np.linalg.norm(m, axis=1, keepdims=True)
            n[n == 0] = 1.0
            return m / n

        sims = _unit(item_vecs) @ _unit(sec_vecs).T
        for i, it in enumerate(no_mapeados):
            j = int(sims[i].argmax())
            if float(sims[i][j]) >= _UMBRAL_EMB:
                asignaciones[it["numero"]] = toc_nombres[j]
    except Exception as exc:
        logger.warning(f"[rubrica] Embeddings fallback no disponible ({exc}).")
    return asignaciones


def _mapear_items_a_secciones(
    items: list[dict], toc_nombres: list[str]
) -> tuple[dict[str, list[int]], list[dict]]:
    """Mapea ítems→secciones combinando LLM + reglas transversales + embeddings.

    Devuelve (mapa, items_ausentes). `items_ausentes` son criterios de la rúbrica
    cuyo contenido NO vive en ninguna sección de ESTE proyecto (p. ej. financiamiento
    cuando el proyecto no tiene esa sección): cuentan para el máximo pero el estudiante
    no los tiene → se reportan, no se pierden en silencio.
    """
    if not items or not toc_nombres:
        return {}, []

    id_to_name = {f"S{i + 1}": n for i, n in enumerate(toc_nombres)}
    items_txt = "\n".join(f"{it['numero']}. {it.get('descripcion', '')}" for it in items)
    secciones_txt = "\n".join(f"[S{i + 1}] {n}" for i, n in enumerate(toc_nombres))

    nums_validos = {it["numero"] for it in items}
    mapa: dict[str, list[int]] = {}
    no_resueltas = 0

    try:
        resp = llm_rapido(temperatura=0.0).invoke([
            SystemMessage(content=_PROMPT_MAPEO.format(items=items_txt, secciones=secciones_txt)),
            HumanMessage(content="Devuelve el mapa de secciones (por ID) a ítems."),
        ])
        # Saneado defensivo: el LLM a veces emite enteros con cero a la izquierda
        # (p. ej. [04, 08]) que NO son JSON válido. Se eliminan antes de parsear.
        contenido = re.sub(r'(?<=[\[,\s])0+(\d)', r'\1', resp.content or "")
        data = extraer_json(contenido)
        for clave, nums in ((data or {}).get("mapa") or {}).items():
            nombre = _resolver_seccion(clave, id_to_name, toc_nombres)
            if not nombre:
                no_resueltas += 1
                continue
            actual = mapa.setdefault(nombre, [])
            for n in nums or []:
                try:
                    n_int = int(n)
                except (TypeError, ValueError):
                    continue
                if n_int in nums_validos and n_int not in actual:
                    actual.append(n_int)
    except Exception as exc:
        logger.warning(f"[rubrica] Mapeo LLM falló ({exc}); se usará solo reglas + embeddings.")

    def _ya_mapeado(num: int) -> bool:
        return any(num in v for v in mapa.values())

    def _agregar(nombre: str, num: int) -> None:
        v = mapa.setdefault(nombre, [])
        if num not in v:
            v.append(num)

    # (1) TRANSVERSALES: la LISTA de referencias → Referencias; el USO de citas/
    # normas/postura → donde se usan fuentes (antecedentes/marco) y, si es de normas,
    # también Referencias. Se evalúan en cada una de esas secciones (no en una sola).
    secs_fuentes = _secs_que_matchean(toc_nombres, _RE_SEC_TEORICO)
    secs_ref     = _secs_que_matchean(toc_nombres, _RE_SEC_REF)
    for it in items:
        desc = it.get("descripcion", "")
        if _RE_REF_ITEM.search(desc):
            for n in (secs_ref or secs_fuentes):
                _agregar(n, it["numero"])
        elif _RE_CITA_USO.search(desc):
            destinos = list(secs_fuentes)
            if _RE_NORMAS.search(desc):
                destinos += secs_ref
            for n in (destinos or secs_ref):
                _agregar(n, it["numero"])

    # (2) FUENTES DE FINANCIAMIENTO: si existe una sección de financiamiento/presupuesto,
    # mapéalo; si NO existe, el proyecto no lo cubre → forzar ausente (y excluir de
    # embeddings, para que no se asigne por error a Recursos/Bienes).
    secs_financ = _secs_que_matchean(toc_nombres, _RE_SEC_FINANC)
    forzar_ausente: set[int] = set()
    for it in items:
        if not _RE_FINANC_FUENTE.search(it.get("descripcion", "")):
            continue
        num = it["numero"]
        if secs_financ:
            _agregar(secs_financ[0], num)
        else:
            for v in mapa.values():
                if num in v:
                    v.remove(num)
            forzar_ausente.add(num)

    # (3) EMBEDDINGS: ítems que el LLM y las reglas no ubicaron (y no forzados a
    # ausente) → sección de nombre más similar (si supera el umbral de confianza).
    no_mapeados = [
        it for it in items
        if not _ya_mapeado(it["numero"]) and it["numero"] not in forzar_ausente
    ]
    for num, nombre in _asignar_por_embeddings(no_mapeados, toc_nombres).items():
        _agregar(nombre, num)

    # (4) AUSENTES: ítems que la rúbrica califica pero cuyo contenido no vive en
    # ninguna sección de este proyecto (cuentan para el máximo, se reportan).
    items_ausentes = [
        {"numero": it["numero"], "descripcion": it.get("descripcion", "")}
        for it in items if not _ya_mapeado(it["numero"])
    ]

    asignados = sum(len(v) for v in mapa.values())
    logger.info(
        f"[rubrica] Mapa ítem→sección: {len(mapa)}/{len(toc_nombres)} secciones, "
        f"{asignados} asignaciones, {len(items_ausentes)} ítems ausentes"
        + (f" ({no_resueltas} claves del LLM no resueltas)" if no_resueltas else "")
    )
    return mapa, items_ausentes


def procesar_rubrica(pdf_bytes: bytes, estructura_toc: Optional[dict]) -> dict:
    """
    Parsea, valida y mapea una rúbrica PDF.

    Returns:
        dict de rúbrica (items, secciones, escala, tabla_vigesimal, total_items,
        puntaje_maximo, texto_raw) + `mapa_secciones`.

    Raises:
        RubricaInvalida: si está vacía, sin relación o no parseable.
    """
    rubrica = parse_rubrica_pdf(pdf_bytes)
    if rubrica is None or len(rubrica.get("items", [])) < _MIN_ITEMS:
        # Antes de rechazar, da un motivo semántico útil.
        texto_raw = ""
        try:
            from backend.rag.rubric_parser import _extraer_texto  # type: ignore
            texto_raw = _extraer_texto(pdf_bytes)
        except Exception:
            pass
        _validar_es_rubrica(texto_raw)
        raise RubricaInvalida(
            "No pude extraer ítems numerados de la rúbrica. Debe tener ítems "
            "(01, 02, …) y secciones visibles, en PDF nativo (no escaneado)."
        )

    _validar_es_rubrica(rubrica.get("texto_raw", ""))

    toc = _toc_nombres(estructura_toc)
    mapa, ausentes = _mapear_items_a_secciones(rubrica["items"], toc)
    rubrica["mapa_secciones"] = mapa
    rubrica["items_ausentes"] = ausentes
    rubrica["mapa_toc_firma"] = _firma_toc(toc)
    return rubrica


def _toc_nombres(estructura_toc: Optional[dict]) -> list[str]:
    pares = sorted((estructura_toc or {}).items(), key=lambda x: x[1])
    return [n for n, _ in pares]


def mapear_rubrica(rubrica: dict, estructura_toc: Optional[dict]) -> dict:
    """Calcula (o recalcula) `mapa_secciones` de una rúbrica ya parseada contra un TOC.

    Se usa cuando la rúbrica se subió ANTES del proyecto: al indexar el proyecto se
    mapea contra sus secciones reales.
    """
    if not rubrica or not rubrica.get("items"):
        return rubrica
    toc = _toc_nombres(estructura_toc)
    mapa, ausentes = _mapear_items_a_secciones(rubrica["items"], toc)
    rubrica["mapa_secciones"] = mapa
    rubrica["items_ausentes"] = ausentes
    rubrica["mapa_toc_firma"] = _firma_toc(toc)
    return rubrica
