"""
Revisión completa del proyecto en 3 fases — cobertura total, sin quemar tokens.

Fase 1 (barrido por sección):  evalúa TODAS las secciones del proyecto. Cada una
                               se diagnostica con su contenido COMPLETO (ventaneo
                               si es muy larga) contra SUS ítems de rúbrica. Nada
                               se trunca ni se queda sin leer.
Fase 2 (profundización):       la red multiagente completa corre UNA sola vez sobre el
                               NÚCLEO de coherencia (título · problema · objetivos ·
                               hipótesis · variables + alineación con tipo/diseño,
                               población/método y marco teórico↔metodológico). El redactor
                               REESCRIBE solo los subpuntos de más peso en la rúbrica con
                               margen de mejora (máx. 3, criterio "peso + margen"); el resto
                               lleva solo la explicación del porqué de su nota.
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

import re
import uuid
import logging
import threading
import unicodedata
from typing import Iterator, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import (
    RUBRICA_ITEMS_UPAO,
    _buscar_items_seccion,
    _seccion_rubrica_para,
    _prefijo_num,
)
from .llm import llm_rapido, extraer_json
from .grafo import ejecutar_seccion

logger = logging.getLogger(__name__)

_MAX_CHARS_VENTANA       = 7000   # presupuesto por llamada de diagnóstico
_MIN_CHARS_UNIDAD        = 120    # por debajo: prácticamente solo título → no se diagnostica

_PROMPT_BARRIDO = """Eres un auditor académico experto en proyectos de tesis.
Califica el texto de UNA sección contra los ÍTEMS de rúbrica dados. Sé crítico, realista y concreto.
Escala POR ÍTEM: 0 a {escala} (0 = no cumple/ausente; {escala} = excelente; usa valores intermedios).

{enfoque}

REGLA DE TIPO: si un ítem exige algo que el ENFOQUE NO requiere (p. ej. hipótesis en estudio
cualitativo, 2.ª variable cuando el tipo usa una sola, operacionalización donde no corresponde),
ponle "aplica": false y NO lo penalices; explica en "razon" que por el tipo no es exigible.

Reglas:
- Evalúa el contenido de ESTA sección. Para ítems RELACIONALES (que piden coherencia con OTRA
  parte del proyecto: p. ej. "el objetivo guarda relación con el problema", "las hipótesis se
  relacionan con el problema", "el tipo/método concuerda con el problema"), APÓYATE en el
  CONTEXTO DE COHERENCIA de abajo para verificar esa relación. No penalices por contenido ajeno a
  la sección que no sea relacional.
- Para ítems del tipo "el problema/la pregunta está claramente formulado", evalúa la PREGUNTA o el
  enunciado del problema tal como aparece (formulación / problema central).
- Califica CADA ítem listado, usando su número exacto.
- JUSTIFICA SIEMPRE la nota: si el puntaje NO es el máximo ({escala}), la "razon" DEBE indicar,
  concreto y accionable, QUÉ FALTA para llegar al máximo (no basta con decir que "cumple
  adecuadamente"). Si es el máximo, di brevemente por qué cumple del todo.

Responde SOLO con JSON válido:
{{"items": [{{"numero": <int>, "puntaje": <0-{escala}>, "aplica": true, "razon": "qué cumple y, si no es el máximo, qué falta concretamente para llegar a {escala}"}}],
  "fortalezas": ["frase corta", ...],
  "debilidades": ["frase corta y accionable", ...]}}
Máximo 3 fortalezas y 3 debilidades.

CONTEXTO DE COHERENCIA (otras secciones del proyecto — úsalo SOLO para verificar ítems relacionales):
{coherencia}

ÍTEMS DE LA RÚBRICA APLICABLES A ESTA SECCIÓN:
{criterios}

SECCIÓN EVALUADA: {seccion}
{nota_ventana}
"""

_PROMPT_SINTESIS = """Eres el mentor académico principal. Con los diagnósticos por sección
de un proyecto de tesis, redacta un informe ejecutivo BREVE en markdown y español con:
1. "## Diagnóstico general" — 3-4 frases sobre el estado global del proyecto.
2. "## Plan de acción recomendado" — 4-6 pasos concretos y priorizados.
NO reescribas la tesis. NO inventes contenido que no esté en los diagnósticos.
Máximo ~300 palabras (la calificación por ítem se muestra aparte en una tabla)."""

_PROMPT_TRAZABILIDAD = """Eres un metodólogo. Verifica la TRAZABILIDAD del proyecto: que el tipo y
diseño declarados concuerden entre sí y con el problema, objetivos, hipótesis y variables.
{enfoque}

Presta especial atención a si el tipo/diseño DECLARADO coincide con lo que el proyecto realmente
hace: si declara un tipo pero mezcla elementos de otro (p. ej. dice CUANTITATIVA pero tiene
hipótesis o categorías cualitativas → en realidad sería MIXTA), márcalo como NO coherente y, en las
observaciones, recomienda los DOS caminos: alinear el tipo/diseño a lo que hace, o ajustar ese
elemento para cumplir con el tipo declarado. Fundamenta en criterio metodológico; no inventes citas.

Responde SOLO JSON válido:
{{"coherente": true|false, "observaciones": "2-4 frases: qué encaja y qué no (incongruencias); si el
tipo declarado no concuerda con el contenido, dilo y da la recomendación dual; si algo no aplica por
el tipo, dilo y no lo trates como error"}}

FRAGMENTOS CLAVE DEL PROYECTO (título, problema, objetivos, hipótesis, variables, tipo/diseño):
{contexto}
"""


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


def _norm_sec(s: str) -> str:
    """Nombre de sección normalizado (sin acentos/puntuación) para comparar."""
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _es_desc_o_igual(seccion: str, ancla: str) -> bool:
    """True si `seccion` ES la sección `ancla` o una SUBsección suya (por prefijo
    numérico; o por nombre normalizado cuando no hay número, p. ej. 'Título')."""
    ps, pa = _prefijo_num(seccion), _prefijo_num(ancla)
    if ps and pa:
        return ps == pa or ps.startswith(pa + ".")
    return _norm_sec(seccion) == _norm_sec(ancla)


def _coincide_seccion(seccion_real: str, ancla: str) -> bool:
    """La sección real cae bajo el ancla (subsección) O la contiene (capítulo padre)."""
    return _es_desc_o_igual(seccion_real, ancla) or _es_desc_o_igual(ancla, seccion_real)


def _anclas_por_item(rubrica: dict | None) -> dict[int, list[str]]:
    """Para cada ítem, sus secciones-ANCLA = las secciones mapeadas MÁS específicas
    (se descarta un ancestro si otra subsección suya también está mapeada al ítem).

    Por qué: el `mapa_secciones` (claves = nombres REALES del TOC) suele mapear un
    ítem a un capítulo Y a su hoja (p. ej. '1.', '1.1.', '1.1.2.'). Anclar a la hoja
    evita evaluar el ítem en todo el capítulo, y comparar por nombre real (no por la
    plantilla UPAO) corrige el bug de 'Ausente aunque exista'.
    """
    mapa = (rubrica or {}).get("mapa_secciones") or {}
    por_item: dict[int, list[str]] = {}
    for sec, nums in mapa.items():
        for n in nums or []:
            por_item.setdefault(n, [])
            if sec not in por_item[n]:
                por_item[n].append(sec)

    anclas: dict[int, list[str]] = {}
    for n, secs in por_item.items():
        hojas = []
        for s in secs:
            ps = _prefijo_num(s)
            tiene_descendiente = bool(ps) and any(
                s2 != s and _prefijo_num(s2).startswith(ps + ".") for s2 in secs
            )
            if not tiene_descendiente:
                hojas.append(s)
        anclas[n] = hojas or secs
    return anclas


def _items_de_unidad(unidad: str, secciones_raw: list[str], rubrica: dict | None,
                     anclas: dict[int, list[str]] | None = None) -> list[dict]:
    """Ítems de rúbrica (con número y descripción) aplicables a la unidad."""
    if rubrica:
        # Rúbrica CON mapa → asignación precisa por ancla contra los nombres REALES
        # de las secciones que componen la unidad (no la plantilla UPAO).
        if anclas is not None:
            por_num = {it["numero"]: it for it in (rubrica.get("items") or [])}
            return [
                por_num[num] for num in sorted(anclas)
                if num in por_num
                and any(_coincide_seccion(raw, a) for raw in secciones_raw for a in anclas[num])
            ]
        # Rúbrica SIN mapa → lookup por nombre (comportamiento histórico).
        from backend.rag.rubric_parser import items_para_seccion
        items = items_para_seccion(rubrica, unidad)
        if not items:
            for s in secciones_raw:
                items = items_para_seccion(rubrica, s)
                if items:
                    break
        return items or []
    nums = _buscar_items_seccion(unidad)
    if not nums:
        for s in secciones_raw:
            nums = _buscar_items_seccion(s)
            if nums:
                break
    return [{"numero": n, "descripcion": RUBRICA_ITEMS_UPAO.get(n, "")} for n in (nums or [])]


def _digest_coherencia(unidades: list[dict], max_por_sec: int = 450, tope: int = 3500) -> str:
    """Resumen compacto del ESQUELETO (título · problema/pregunta · objetivos · hipótesis ·
    variables · tipo/diseño · población) para que el barrido pueda juzgar ítems RELACIONALES
    (p. ej. 'el objetivo guarda relación con el problema') que viven en otra sección."""
    partes = []
    for u in unidades:
        if _es_nucleo(u["unidad"]):
            txt = " ".join(u["chunks"]).strip()[:max_por_sec]
            if txt:
                partes.append(f"[{u['unidad']}] {txt}")
    return "\n".join(partes)[:tope] or "(sin contexto disponible)"


def _diagnosticar_unidad(llm, u: dict, rubrica: dict | None, enfoque: str, escala: int,
                         anclas: dict[int, list[str]] | None = None,
                         coherencia: str = "") -> dict | None:
    """Califica los ÍTEMS de rúbrica mapeados a la unidad (1 llamada). None si no tiene ítems."""
    items = _items_de_unidad(u["unidad"], u["secciones_raw"], rubrica, anclas)
    if not items:
        return None

    criterios = "\n".join(f"{it['numero']:02d}. {it.get('descripcion', '')}" for it in items)
    contenido = "\n\n".join(u["chunks"])[: _MAX_CHARS_VENTANA * 2]
    try:
        resp = llm.invoke([
            SystemMessage(content=_PROMPT_BARRIDO.format(
                escala=escala, enfoque=enfoque, criterios=criterios,
                seccion=u["unidad"], nota_ventana="",
                coherencia=coherencia or "(sin contexto disponible)",
            )),
            HumanMessage(content=contenido),
        ])
        data = extraer_json(resp.content) or {}
    except Exception as exc:
        logger.warning(f"[revision_completa] Barrido falló en '{u['unidad']}': {exc}")
        data = {}

    nums_validos = {it["numero"] for it in items}
    eval_items: dict[int, dict] = {}
    for r in (data.get("items") or []):
        try:
            num = int(r.get("numero"))
        except (TypeError, ValueError):
            continue
        if num not in nums_validos:
            continue
        try:
            p = max(0, min(int(escala), int(round(float(r.get("puntaje", 0))))))
        except (TypeError, ValueError):
            p = 0
        eval_items[num] = {
            "puntaje": p,
            "aplica":  bool(r.get("aplica", True)),
            "razon":   (r.get("razon") or "")[:300],
        }
    # Ítems mapeados que el LLM no devolvió → 0 (presentes pero no calificados).
    for it in items:
        eval_items.setdefault(it["numero"], {"puntaje": 0, "aplica": True, "razon": ""})

    return {
        "unidad":        u["unidad"],
        "secciones_raw": u["secciones_raw"],
        "eval":          eval_items,
        "fortalezas":    [f for f in (data.get("fortalezas") or []) if f][:3],
        "debilidades":   [d for d in (data.get("debilidades") or []) if d][:3],
    }


def _recalificar(llm, items: list[dict], texto: str, enfoque: str, escala: int,
                 coherencia: str = "") -> dict:
    """Re-puntúa una lista de ítems (con número int) contra un TEXTO (1 llamada).

    Se usa para re-calificar los subpuntos REESCRITOS del núcleo contra el texto
    mejorado, de modo que la nota refleje la mejora. Devuelve {num: {puntaje, aplica, razon}}.
    """
    if not items or not (texto or "").strip():
        return {}
    criterios = "\n".join(f"{it['numero']:02d}. {it.get('descripcion', '')}" for it in items)
    try:
        resp = llm.invoke([
            SystemMessage(content=_PROMPT_BARRIDO.format(
                escala=escala, enfoque=enfoque, criterios=criterios,
                seccion="Subpuntos reescritos del núcleo", nota_ventana="",
                coherencia=coherencia or "(sin contexto)",
            )),
            HumanMessage(content=texto[: _MAX_CHARS_VENTANA * 2]),
        ])
        data = extraer_json(resp.content) or {}
    except Exception as exc:
        logger.warning(f"[revision_completa] Recalificación falló: {exc}")
        return {}

    nums_validos = {it["numero"] for it in items}
    out: dict[int, dict] = {}
    for r in (data.get("items") or []):
        try:
            num = int(r.get("numero"))
        except (TypeError, ValueError):
            continue
        if num not in nums_validos:
            continue
        try:
            p = max(0, min(int(escala), int(round(float(r.get("puntaje", 0))))))
        except (TypeError, ValueError):
            p = 0
        out[num] = {"puntaje": p, "aplica": bool(r.get("aplica", True)),
                    "razon": (r.get("razon") or "")[:300]}
    return out


def _consolidar_calificacion(diagnosticos: list[dict], items_all: list[dict],
                             ausentes: list[dict], escala: int) -> dict:
    """Une las evaluaciones por unidad en una calificación por ítem (todos los ítems)."""
    por_item: dict[int, list[dict]] = {}
    secs_item: dict[int, list[str]] = {}
    for d in diagnosticos:
        for num, ev in (d.get("eval") or {}).items():
            por_item.setdefault(num, []).append(ev)
            secs_item.setdefault(num, [])
            if d["unidad"] not in secs_item[num]:
                secs_item[num].append(d["unidad"])

    desc = {it["numero"]: it.get("descripcion", "") for it in items_all}
    ausente_nums = {a["numero"] for a in ausentes}

    items_out, total, maximo = [], 0, 0
    umbral_ok = round(escala * 2 / 3)
    for it in items_all:
        num = it["numero"]
        evs = por_item.get(num)
        if not evs:
            items_out.append({"numero": num, "descripcion": desc.get(num, ""), "secciones": [],
                              "puntaje": 0, "maximo": escala, "estado": "ausente",
                              "razon": "Tu proyecto no incluye contenido para este criterio."})
            maximo += escala
            continue
        no_aplica = sum(1 for e in evs if not e.get("aplica", True)) >= (len(evs) + 1) // 2
        if no_aplica:
            razon = next((e.get("razon") for e in evs if not e.get("aplica", True)), "")
            items_out.append({"numero": num, "descripcion": desc.get(num, ""),
                              "secciones": secs_item.get(num, []), "puntaje": None,
                              "maximo": escala, "estado": "na", "razon": razon})
            continue  # N/A por tipo: no cuenta al máximo
        puntajes = [e["puntaje"] for e in evs if e.get("aplica", True)]
        p = round(sum(puntajes) / len(puntajes)) if puntajes else 0
        razon = next((e.get("razon") for e in evs if e.get("razon")), "")
        items_out.append({"numero": num, "descripcion": desc.get(num, ""),
                          "secciones": secs_item.get(num, []), "puntaje": p, "maximo": escala,
                          "estado": "ok" if p >= umbral_ok else "bajo", "razon": razon})
        total += p
        maximo += escala
    _ = ausente_nums  # (los ausentes ya caen en la rama "sin evs")
    return {"puntaje": total, "maximo": maximo,
            "items": sorted(items_out, key=lambda x: x["numero"])}


def _evaluar_trazabilidad(llm, unidades: list[dict], enfoque: str) -> dict:
    """Veredicto global de trazabilidad (1 llamada) sobre las secciones clave."""
    import unicodedata
    def _n(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    claves = ("titulo", "problema", "objetivo", "hipotesis", "variable", "tipo", "diseno", "metodo")
    partes = []
    for u in unidades:
        if any(k in _n(u["unidad"]) for k in claves):
            partes.append(f"[{u['unidad']}]\n" + ("\n".join(u['chunks'])[:1500]))
    contexto = "\n\n".join(partes)[:9000]
    if not contexto.strip():
        return {"coherente": True, "observaciones": ""}
    try:
        resp = llm.invoke([
            SystemMessage(content=_PROMPT_TRAZABILIDAD.format(enfoque=enfoque, contexto=contexto)),
            HumanMessage(content="Evalúa la trazabilidad del proyecto."),
        ])
        data = extraer_json(resp.content) or {}
        return {"coherente": bool(data.get("coherente", True)),
                "observaciones": (data.get("observaciones") or "")[:1200]}
    except Exception as exc:
        logger.warning(f"[revision_completa] Trazabilidad falló: {exc}")
        return {"coherente": True, "observaciones": ""}


# Esqueleto de coherencia/trazabilidad: lo que SÍ profundiza la red.
# Patrones del ESQUELETO de coherencia. Amplios para cubrir las distintas frases de
# las 5 rúbricas por tipo (cuanti/cuali/mixto/tecnológico/innovación), no solo el TOC UPAO.
_NUCLEO_PATRONES = [
    re.compile(r"t[íi]tulo", re.I),
    re.compile(r"(problema|planteamiento|formulaci[oó]n|pregunta|\breto)", re.I),
    re.compile(r"objetivo", re.I),
    re.compile(r"(hip[oó]tesis|\bsupuesto|categor[ií]a)", re.I),   # \b evita 'preSUPUESTO'
    re.compile(r"(variable|operacionaliz)", re.I),
    re.compile(r"(tipo|m[eé]todo|metodolog|dise[ñn]o|paradigma)", re.I),
    re.compile(r"(poblaci[oó]n|muestra|participante|segmento)", re.I),
]


def _es_nucleo(nombre: str) -> bool:
    return any(p.search(nombre or "") for p in _NUCLEO_PATRONES)


# CORE del núcleo: SOLO lo que se REESCRIBE (título · problema · objetivos · hipótesis ·
# variables). Población/método/tipo/diseño/marco son CONTEXTO de alineación, no se reescriben.
_CORE_PATRONES = [
    re.compile(r"t[íi]tulo", re.I),
    re.compile(r"(problema|planteamiento|formulaci[oó]n|pregunta|\breto)", re.I),
    re.compile(r"objetivo", re.I),
    re.compile(r"(hip[oó]tesis|\bsupuesto|categor[ií]a)", re.I),   # \b evita 'preSUPUESTO'
    re.compile(r"(variable|operacionaliz)", re.I),
]


def _es_core(nombre: str) -> bool:
    return any(p.search(nombre or "") for p in _CORE_PATRONES)


# Una sección que es un CUADRO/tabla (operacionalización, matriz de consistencia…) NO es la
# DEFINICIÓN del subpunto. Para variables, preferimos «Variable independiente/dependiente»
# (donde se definen tal cual) antes que los cuadros.
_RE_CUADRO = re.compile(r"(operacionaliz|matriz|consistencia|cuadro|tabla|esquema)", re.I)


def _es_cuadro(nombre: str) -> bool:
    return bool(_RE_CUADRO.search(nombre or ""))


def _es_encabezado_capitulo(nombre: str) -> bool:
    """Encabezado de capítulo (prefijo de un solo nivel: '1', '2'…). No es un
    subpunto del núcleo: sus hojas (1.1.2, 3.2…) ya entran por separado, así que
    incluirlo traería el capítulo ENTERO y duplicaría contenido."""
    pref = _prefijo_num(nombre)
    return bool(pref) and "." not in pref


def _secciones_nucleo(toc_nombres: list[str]) -> list[str]:
    return [n for n in toc_nombres if _es_nucleo(n) and not _es_encabezado_capitulo(n)]


def _plan_nucleo(nucleo: list[str], diagnosticos: list[dict], escala: int, tope: int = 3) -> dict:
    """Decide qué subpuntos del núcleo se REESCRIBEN y cuáles solo se OBSERVAN.

    Criterio (elección del usuario): "peso + margen". Prioridad = peso × brecha, donde
    peso = nº de ítems de rúbrica aplicables al subpunto y brecha = escala − nota promedio.
    Así se reescriben los subpuntos que más pesan en la rúbrica Y tienen margen de mejora
    (no se gasta el redactor en lo que ya está bien aunque pese). El resto lleva solo la
    explicación del porqué de su nota (las razones del barrido). Máximo `tope` reescritos.
    """
    diag_por_unidad = {d["unidad"]: d for d in diagnosticos}
    filas: list[dict] = []
    vistas: set[str] = set()
    # Procesa primero las DEFINICIONES y deja los cuadros al final: así, cuando varias
    # entradas del TOC caen en la misma unidad de rúbrica (p. ej. «2.2.1 Variable
    # independiente» y «3.3 Variables (Operacionalización)»), se conserva la definición.
    core_secs = sorted((s for s in nucleo if _es_core(s)), key=lambda s: 1 if _es_cuadro(s) else 0)
    for sec in core_secs:
        unidad = _seccion_rubrica_para(sec) or sec
        if unidad in vistas:          # dos entradas del TOC en la misma unidad de rúbrica
            continue
        d = diag_por_unidad.get(unidad)
        if not d:
            continue                  # sin ítems de rúbrica mapeados → no es candidato
        evs = [e for e in d["eval"].values() if e.get("aplica", True)]
        if not evs:
            continue
        vistas.add(unidad)
        peso  = len(evs)
        score = sum(e["puntaje"] for e in evs) / peso
        gap   = max(0.0, escala - score)
        razones = [e.get("razon") for e in d["eval"].values() if e.get("razon")][:3]
        filas.append({
            "seccion":   sec,
            "peso":      peso,
            "puntaje":   round(score, 1),
            "maximo":    escala,
            "prioridad": peso * gap,
            "razones":   razones,
        })

    filas.sort(key=lambda x: x["prioridad"], reverse=True)
    reescribir = [f["seccion"] for f in filas if f["prioridad"] > 0][:tope]
    rset = set(reescribir)
    observar = [
        {"seccion": f["seccion"], "puntaje": f["puntaje"], "maximo": f["maximo"],
         "razones": f["razones"]}
        for f in filas if f["seccion"] not in rset
    ]
    return {"reescribir": reescribir, "observar": observar}


def _contexto_nucleo(doc, nucleo: list[str]) -> tuple:
    """Arma el contexto combinado del núcleo (1 sola corrida de la red)."""
    from backend.rag import recuperar_contexto, recuperar_contexto_teorico
    from .deps import get_biblioteca

    partes = []
    for sec in nucleo:
        try:
            cont = recuperar_contexto(doc.vector_store, sec)
        except Exception:
            cont = ""
        if cont and cont.strip():
            partes.append(f"### {sec}\n{cont.strip()[:2500]}")
    contexto_tesis = "\n\n".join(partes)

    # Marco teórico para verificar alineación marco teórico ↔ metodológico.
    toc = list(doc.estructura_toc or {})
    deps_secs = [n for n in toc if re.search(r"(antecedent|base te[oó]ric|marco te[oó]ric)", n, re.I)]
    deps = []
    for s in deps_secs[:3]:
        try:
            c = recuperar_contexto(doc.vector_store, s)
        except Exception:
            c = ""
        if c and c.strip():
            deps.append(f"### {s}\n{c.strip()[:1800]}")
    contexto_deps = "\n\n".join(deps)

    try:
        contexto_teo = recuperar_contexto_teorico(
            get_biblioteca(), "trazabilidad tipo diseño población método variables hipótesis"
        )
    except Exception:
        contexto_teo = ""
    return contexto_tesis, contexto_deps, contexto_teo


def _estado_juez(pts: float, mx: float) -> str:
    """Estado de un ítem del juez (escala ponderada): ok / bajo / ausente."""
    if mx <= 0:
        return "na"
    if pts <= 0:
        return "ausente"
    return "ok" if (pts / mx) >= 0.66 else "bajo"


def _titulo_rubrica_limpio(titulo: str) -> str:
    """Quita la coletilla '[Máximo: N pts]' y escapes del título de sección de rúbrica."""
    t = re.sub(r"\\?\[\s*M[aá]ximo[^\]]*\]", "", titulo or "")
    return t.replace("\\", "").strip(" .")


def _calificar_por_tipo(doc, tipo: Optional[str], coherencia: str, cancelar: threading.Event):
    """Generador: califica el proyecto con la rúbrica del TIPO vía LLM-as-judge (1 modelo).

    Itera las secciones de la rúbrica del tipo (cuanti→rubrica.md, cuali/mixto/tecnológico/
    innovación→sus archivos), recupera el contenido por sección y lo califica con un solo
    modelo (todos los ítems, escala ponderada /100). Va emitiendo progreso; el último evento
    es {'tipo':'_cal', 'calificacion':..., 'por_seccion':...}.
    """
    import os
    from evaluator.metrics.llm_judge import (
        cargar_rubrica_metodologica, _parsear_secciones_rubrica, _ejecutar_un_juez,
    )
    from backend.rag import recuperar_contexto, limpiar_marcas_rag

    rubrica_md = cargar_rubrica_metodologica(tipo)
    secciones = _parsear_secciones_rubrica(rubrica_md)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    items_cal: list[dict] = []
    por_seccion: dict[str, dict] = {}
    for _num, titulo_raw, cuerpo in secciones:
        if cancelar.is_set():
            return
        titulo = _titulo_rubrica_limpio(titulo_raw)
        yield {"tipo": "progreso", "detalle": f"Métrica — «{titulo}»…"}
        try:
            cont = limpiar_marcas_rag(recuperar_contexto(doc.vector_store, titulo))
        except Exception:
            cont = ""
        texto = cont or "(sección sin contenido localizable en el proyecto)"
        # Para secciones del núcleo (relacionales) añade el esqueleto para juzgar la coherencia.
        if _es_nucleo(titulo) and coherencia:
            texto = (cont + "\n\n## OTRAS SECCIONES (solo para verificar coherencia/relación)\n"
                     + coherencia)[:14000]
        try:
            ev = _ejecutar_un_juez("gpt-4o-mini", 0.0, titulo, texto, cuerpo, api_key)
        except Exception as exc:
            logger.warning(f"[revision_completa] Juez falló en '{titulo}': {exc}")
            ev = None
        if not ev or not ev.items:
            continue
        sec_items = []
        for it in ev.items:
            d = {
                "numero":      str(it.item_id),
                "descripcion": it.descripcion,
                "secciones":   [titulo],
                "puntaje":     round(float(it.pts_obtenido), 2),
                "maximo":      round(float(it.pts_max), 2),
                "estado":      _estado_juez(float(it.pts_obtenido), float(it.pts_max)),
                "razon":       (it.razon or "")[:400],
            }
            items_cal.append(d)
            sec_items.append(d)
        por_seccion[titulo] = {
            "items": sec_items,
            "pts":   round(sum(i["puntaje"] for i in sec_items), 1),
            "max":   round(sum(i["maximo"] for i in sec_items), 1),
        }

    cal = {
        "puntaje": round(sum(i["puntaje"] for i in items_cal), 1),
        "maximo":  round(sum(i["maximo"] for i in items_cal), 1),
        "items":   items_cal,
    }
    yield {"tipo": "_cal", "calificacion": cal, "por_seccion": por_seccion}


def _plan_nucleo_juez(por_seccion: dict, tope: int = 3) -> dict:
    """Plan del núcleo con las notas del juez: reescribe las secciones del núcleo con más
    puntos perdidos (peso × margen); el resto solo se observa. `items` guía al redactor."""
    filas = []
    for titulo, d in por_seccion.items():
        if not _es_nucleo(titulo):
            continue
        gap = max(0.0, d["max"] - d["pts"])
        razones = [i["razon"] for i in d["items"]
                   if i["estado"] in ("bajo", "ausente") and i["razon"]][:3]
        filas.append({"seccion": titulo, "puntaje": d["pts"], "maximo": d["max"],
                      "prioridad": gap, "razones": razones})
    filas.sort(key=lambda x: x["prioridad"], reverse=True)
    reescribir = [f["seccion"] for f in filas if f["prioridad"] > 0][:tope]
    rset = set(reescribir)
    observar = [{"seccion": f["seccion"], "puntaje": f["puntaje"], "maximo": f["maximo"],
                 "razones": f["razones"]} for f in filas if f["seccion"] not in rset]
    items = [{"numero": i["numero"], "descripcion": i["descripcion"]}
             for t, d in por_seccion.items() if _es_nucleo(t) for i in d["items"]]
    return {"reescribir": reescribir, "observar": observar, "items": items}


def ejecutar_revision_completa(
    doc,
    max_iteraciones: int,
    cancelar: threading.Event,
) -> Iterator[dict]:
    """Generador de eventos SSE para la revisión completa del proyecto.

    Fase 1 — Calificación con LA RÚBRICA DEL ESTUDIANTE (barrido 0-ESCALA_MAX, todos
             los ítems): es la nota oficial ("Calificación con tu rúbrica").
    Fase 2 — Métrica complementaria: rúbrica del TIPO vía LLM-as-judge (1 modelo, /100).
    Fase 3 — Núcleo: reescribe SOLO título·problema·objetivos·hipótesis·variables
             (población/método/diseño/marco = contexto de alineación), con las NOTAS
             REALES del barrido + trazabilidad.
    """
    from .tipo_investigacion import obtener_tipo_diseno
    from backend.enfoque import bloque_enfoque, ETIQUETAS, normalizar_tipo
    from backend.config import ESCALA_MAX

    llm = llm_rapido(temperatura=0.1)
    tipo_inv, diseno = obtener_tipo_diseno(doc)
    enfoque = bloque_enfoque(tipo_inv, diseno)
    etiqueta_tipo = ETIQUETAS.get(normalizar_tipo(tipo_inv), "—")

    rubrica = getattr(doc, "rubrica", None)
    if rubrica and rubrica.get("items"):
        items_all = rubrica["items"]
        ausentes  = rubrica.get("items_ausentes") or []
    else:
        items_all = [{"numero": n, "descripcion": d} for n, d in RUBRICA_ITEMS_UPAO.items()]
        ausentes  = []

    # ── FASE 1: Calificación con TU rúbrica (barrido por ítem, 0-ESCALA_MAX) ──
    yield {"tipo": "fase", "fase": "barrido",
           "detalle": "Fase 1/4 — Calificando con tu rúbrica…"}
    unidades = _contenido_por_unidad_rubrica(doc)
    anclas = _anclas_por_item(rubrica) if (rubrica and rubrica.get("mapa_secciones")) else None
    coherencia = _digest_coherencia(unidades)
    diagnosticos: list[dict] = []
    fortalezas: list[str] = []
    debilidades: list[str] = []
    for u in unidades:
        if cancelar.is_set():
            yield {"tipo": "cancelado"}
            return
        if sum(len(c) for c in u["chunks"]) < _MIN_CHARS_UNIDAD:
            continue
        yield {"tipo": "progreso", "detalle": f"Calificando «{u['unidad']}»…"}
        diag = _diagnosticar_unidad(llm, u, rubrica, enfoque, ESCALA_MAX, anclas, coherencia)
        if not diag:
            continue
        diagnosticos.append(diag)
        aplic = [e["puntaje"] for e in diag["eval"].values() if e.get("aplica", True)]
        prom  = round(sum(aplic) / len(aplic), 1) if aplic else ESCALA_MAX
        for f in diag["fortalezas"]:
            if f not in fortalezas:
                fortalezas.append(f)
        for w in diag["debilidades"]:
            if w not in debilidades:
                debilidades.append(w)
        yield {"tipo": "diagnostico", "capitulo": diag["unidad"],
               "puntaje": prom, "debilidades": diag["debilidades"]}
    if not diagnosticos:
        yield {"tipo": "error", "detalle": "No se pudo extraer contenido evaluable del documento."}
        return
    calificacion = _consolidar_calificacion(diagnosticos, items_all, ausentes, ESCALA_MAX)

    # ── FASE 2: Métrica complementaria — rúbrica del TIPO (LLM-as-judge, /100) ──
    yield {"tipo": "fase", "fase": "metricas",
           "detalle": f"Fase 2/4 — Métrica LLM-as-judge (rúbrica {etiqueta_tipo})…"}
    metricas: Optional[dict] = None
    cal_juez: Optional[dict] = None
    for ev in _calificar_por_tipo(doc, tipo_inv, coherencia, cancelar):
        if ev["tipo"] == "_cal":
            cal_juez = ev["calificacion"]
        else:
            yield ev
    if cancelar.is_set():
        yield {"tipo": "cancelado"}
        return
    if cal_juez and cal_juez["items"]:
        metricas = {"tipo": etiqueta_tipo, "fuente": "LLM-as-judge", "calificacion": cal_juez}

    yield {"tipo": "fase", "fase": "trazabilidad", "detalle": "Verificando trazabilidad global…"}
    trazabilidad = _evaluar_trazabilidad(llm, unidades, enfoque)

    def _prom_unidad(d):
        aplic = [e["puntaje"] for e in d["eval"].values() if e.get("aplica", True)]
        return sum(aplic) / len(aplic) if aplic else ESCALA_MAX

    # ── FASE 3: Núcleo (solo CORE: título·problema·objetivos·hipótesis·variables) ──
    nucleo = _secciones_nucleo(list(doc.estructura_toc or {}))
    resumenes: list[dict] = []
    nucleo_reescrito: list[str] = []
    if nucleo and any(_es_core(_seccion_rubrica_para(s) or s) for s in nucleo):
        plan = _plan_nucleo(nucleo, diagnosticos, ESCALA_MAX, tope=3)
        nucleo_reescrito = list(plan.get("reescribir") or [])
        _desc = {it["numero"]: it.get("descripcion", "") for it in items_all}
        _nums = sorted({num for d in diagnosticos if _es_core(d["unidad"]) for num in (d.get("eval") or {})})
        plan["items"] = [{"numero": n, "descripcion": _desc.get(n, "")} for n in _nums]
        # Notas REALES del barrido para los ítems CORE (tu rúbrica) → núcleo detalle.
        eval_items, npts, nmax = [], 0.0, 0.0
        for it in calificacion["items"]:
            if it["estado"] == "na":
                continue
            if any(_es_core(s) for s in (it.get("secciones") or [])):
                eval_items.append({"item_numero": it["numero"], "criterio": it["descripcion"],
                                   "puntaje": it["puntaje"], "maximo": it["maximo"],
                                   "observacion": it.get("razon", "")})
                npts += it["puntaje"] or 0
                nmax += it["maximo"]
        eval_override = ({"items": eval_items, "puntaje": round(npts, 1), "maximo": round(nmax, 1)}
                         if eval_items else None)
        n_re = len(plan["reescribir"])
        yield {"tipo": "fase", "fase": "profundizacion",
               "detalle": f"Fase 3/4 — La red reescribe los {n_re} subpunto(s) core del núcleo "
                          "(título·problema·objetivos·hipótesis·variables); el resto lo explica…"}
        ctx = _contexto_nucleo(doc, nucleo)
        seccion_nucleo = "Núcleo de coherencia (título · problema · objetivos · hipótesis · variables)"
        thread_id = str(uuid.uuid4())
        for evento in ejecutar_seccion(doc, seccion_nucleo, max_iteraciones=1,
                                       thread_id=thread_id, cancelar=cancelar,
                                       contexto_override=ctx, modo_nucleo=True,
                                       nucleo_plan=plan, eval_override=eval_override,
                                       metricas_juez=metricas):
            if evento["tipo"] == "seccion_completada":
                if not evento["resumen"].get("vacia"):
                    resumenes.append(evento["resumen"])
            elif evento["tipo"] == "cancelado":
                yield evento
                return
            else:
                yield evento

        # Re-calificar los subpuntos REESCRITOS contra el texto mejorado, para que la nota
        # REFLEJE la mejora (alineada a las observaciones) sin bajar la original.
        # Inicial = notas del barrido (texto original); Final = re-calificación de lo reescrito.
        if resumenes and nucleo_reescrito and eval_items:
            r0 = resumenes[0]
            texto_mej = r0.get("texto_mejorado") or ""
            reescrito_units = {_seccion_rubrica_para(s) or s for s in nucleo_reescrito}
            nums_rg = sorted({n for d in diagnosticos if d["unidad"] in reescrito_units
                              for n in (d.get("eval") or {})})
            items_rg = [{"numero": n, "descripcion": _desc.get(n, "")} for n in nums_rg]
            regrade = _recalificar(llm, items_rg, texto_mej, enfoque, ESCALA_MAX, coherencia)
            if regrade:
                eval_final, fpts = [], 0.0
                for it in eval_items:
                    fila = dict(it)
                    ng = regrade.get(it["item_numero"])
                    base = it["puntaje"] or 0
                    if ng and ng.get("aplica", True) and ng["puntaje"] > base:
                        fila["puntaje"] = ng["puntaje"]
                        if ng.get("razon"):
                            fila["observacion"] = ng["razon"]
                    fpts += fila["puntaje"] or 0
                    eval_final.append(fila)
                det = r0.get("detalle") or {}
                det["evaluacion_final"] = eval_final
                det["puntaje"] = round(fpts, 1)
                r0["puntaje"] = round(fpts, 1)

    # Secciones débiles FUERA del núcleo → sugerir auditarlas aparte.
    sugeridas = [
        d["unidad"] for d in sorted(diagnosticos, key=_prom_unidad)
        if not _es_nucleo(d["unidad"]) and _prom_unidad(d) < ESCALA_MAX * 0.6
    ][:4]

    yield {"tipo": "fase", "fase": "sintesis", "detalle": "Fase 4/4 — Sintetizando informe global…"}

    diag_txt = "\n".join(
        f"- {it['descripcion']}: {it['puntaje']}/{it['maximo']}" if it["estado"] != "na"
        else f"- {it['descripcion']}: N/A (por tipo)"
        for it in calificacion["items"]
    )
    try:
        sintesis = llm.invoke([
            SystemMessage(content=_PROMPT_SINTESIS),
            HumanMessage(content=diag_txt[:6000]),
        ]).content
    except Exception as exc:
        logger.warning(f"[revision_completa] Síntesis falló: {exc}")
        sintesis = "## Diagnóstico general\n\nRevisión completa generada."

    from .grafo import _bloque_seccion_md

    partes = [
        f"# Calificación con tu rúbrica: **{calificacion['puntaje']}/{calificacion['maximo']} pts**\n",
        sintesis,
    ]
    if metricas:
        cj = metricas["calificacion"]
        partes.append(f"\n_Métrica complementaria (rúbrica {etiqueta_tipo}, LLM-as-judge): "
                      f"**{cj['puntaje']}/{cj['maximo']}** — en «Ver análisis completo» → pestaña Métricas._\n")
    if resumenes:
        notas = " · ".join(
            f"{d['unidad']}: {round(_prom_unidad(d)*len([e for e in d['eval'].values() if e.get('aplica',True)]),1)}"
            f"/{len([e for e in d['eval'].values() if e.get('aplica',True)])*ESCALA_MAX}"
            for d in diagnosticos if _es_core(d["unidad"])
        )
        partes.append("\n---\n# Núcleo de coherencia (título · problema · objetivos · hipótesis · variables)\n")
        if notas:
            partes.append(f"**Notas reales (de tu rúbrica):** {notas}\n")
        partes.append(
            "_Se reescribieron los subpuntos core de mayor peso con margen de mejora; el resto lleva "
            "la explicación de su nota. Población/método/diseño se usan como contexto de alineación._\n"
        )
        partes.append("\n\n---\n\n".join(_bloque_seccion_md(r) for r in resumenes))
    if sugeridas:
        partes.append("\n---\n## Secciones que conviene auditar aparte")
        partes.append(
            "Salieron débiles fuera del núcleo. Pídeme revisarlas por separado "
            f"(p. ej. «revisa mi {sugeridas[0]}»):\n"
        )
        partes.extend(f"- {s}" for s in sugeridas)
    if ausentes:
        partes.append("\n---\n## Criterios de tu rúbrica que el proyecto aún no cubre")
        partes.append("Suman al puntaje máximo pero no hay una sección que los contenga; el jurado los espera:\n")
        partes.extend(f"- **Ítem {a['numero']}:** {a['descripcion']}" for a in ausentes)

    informe = "\n".join(partes).strip()

    # Resumen compacto para que el CHAT rápido recuerde esta evaluación (no pierda el hilo).
    _secc_txt = " · ".join(
        f"{d['unidad']} "
        f"{round(_prom_unidad(d) * len([e for e in d['eval'].values() if e.get('aplica', True)]), 1)}"
        f"/{len([e for e in d['eval'].values() if e.get('aplica', True)]) * ESCALA_MAX}"
        for d in diagnosticos
    )
    resumen_chat = {
        "tipo": "completa",
        "texto": (
            f"Última REVISIÓN COMPLETA con la rúbrica del estudiante: "
            f"{calificacion['puntaje']}/{calificacion['maximo']} pts."
            + (f" Métrica complementaria ({etiqueta_tipo}, LLM-judge): "
               f"{metricas['calificacion']['puntaje']}/{metricas['calificacion']['maximo']}."
               if metricas else "")
            + (f" Trazabilidad: {'coherente' if trazabilidad.get('coherente') else 'con observaciones'}"
               f" — {(trazabilidad.get('observaciones') or '')[:300]}" if trazabilidad else "")
            + (f" Puntaje por sección: {_secc_txt}." if _secc_txt else "")
            + (f" Debilidades principales: {'; '.join(debilidades[:5])}." if debilidades else "")
            + (f" Criterios que el proyecto aún NO cubre: "
               f"{', '.join('ítem ' + str(a['numero']) for a in ausentes)}." if ausentes else "")
            + (f" En el núcleo se reescribieron: {', '.join(nucleo_reescrito)}." if nucleo_reescrito else "")
        ),
    }

    yield {
        "tipo": "resultado",
        "informe_md": informe,
        "calificacion": calificacion,
        "metricas": metricas,
        "resumen_chat": resumen_chat,
        "fortalezas": fortalezas[:6],
        "debilidades": debilidades[:6],
        "trazabilidad": trazabilidad,
        "sugeridas": sugeridas,
        "detalles": [r["detalle"] for r in resumenes if r.get("detalle")],
        "resumen": {"profundizadas": [r["seccion"] for r in resumenes], "sugeridas": sugeridas},
    }
