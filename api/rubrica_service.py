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


def _mapear_items_a_secciones(items: list[dict], toc_nombres: list[str]) -> dict[str, list[int]]:
    """Precomputa {sección_TOC: [num_item]} con un LLM usando IDs de sección. Fallback: {}."""
    if not items or not toc_nombres:
        return {}

    id_to_name = {f"S{i + 1}": n for i, n in enumerate(toc_nombres)}
    items_txt = "\n".join(f"{it['numero']}. {it.get('descripcion', '')}" for it in items)
    secciones_txt = "\n".join(f"[S{i + 1}] {n}" for i, n in enumerate(toc_nombres))

    try:
        resp = llm_rapido(temperatura=0.0).invoke([
            SystemMessage(content=_PROMPT_MAPEO.format(items=items_txt, secciones=secciones_txt)),
            HumanMessage(content="Devuelve el mapa de secciones (por ID) a ítems."),
        ])
        # Saneado defensivo: el LLM a veces emite enteros con cero a la izquierda
        # (p. ej. [04, 08]) que NO son JSON válido. Se eliminan antes de parsear.
        contenido = re.sub(r'(?<=[\[,\s])0+(\d)', r'\1', resp.content or "")
        data = extraer_json(contenido)
    except Exception as exc:
        logger.warning(f"[rubrica] Mapeo LLM falló ({exc}); rúbrica sin mapa por sección.")
        return {}

    mapa_raw = (data or {}).get("mapa") or {}
    nums_validos = {it["numero"] for it in items}
    mapa: dict[str, list[int]] = {}
    no_resueltas = 0
    for clave, nums in mapa_raw.items():
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

    asignados = sum(len(v) for v in mapa.values())
    logger.info(
        f"[rubrica] Mapa ítem→sección: {len(mapa)}/{len(toc_nombres)} secciones, "
        f"{asignados} asignaciones"
        + (f" ({no_resueltas} claves del LLM no resueltas)" if no_resueltas else "")
    )
    return mapa


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

    rubrica["mapa_secciones"] = _mapear_items_a_secciones(
        rubrica["items"], _toc_nombres(estructura_toc)
    )
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
    rubrica["mapa_secciones"] = _mapear_items_a_secciones(
        rubrica["items"], _toc_nombres(estructura_toc)
    )
    return rubrica
