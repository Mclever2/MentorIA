
import logging
import re

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import (
    SECCIONES_TESIS,
    prefijos_evaluacion_para_seccion,
    _seccion_rubrica_para,
)

logger = logging.getLogger(__name__)



def _extraer_prefijo(nombre: str) -> str:
    """Extrae el prefijo numérico de sección: '2.1. Título' → '2.1'"""
    m = re.match(r'^(\d[\d\.]*)', nombre.strip())
    return m.group(1).rstrip('.') if m else ""


def _extraer_prefijos_rango(seccion: str) -> list[str]:
    """
    Extrae todos los prefijos de una sección con rango explícito.
    "4.1–4.3 Tipo, Método y Diseño" → ["4.1", "4.2", "4.3"]
    "3.1–3.2 Hipótesis"             → ["3.1", "3.2"]
    "1.2 Objetivos"                 → ["1.2"]
    "III. Referencias"              → []
    """
    m = re.match(r'^(\d[\d\.]*)[\s]*[–\-][\s]*(\d[\d\.]*)', seccion.strip())
    if not m:
        p = _extraer_prefijo(seccion)
        return [p] if p else []
    ini = m.group(1).rstrip('.')
    fin = m.group(2).rstrip('.')
    p_ini = [int(x) for x in ini.split('.')]
    p_fin = [int(x) for x in fin.split('.')]
    if len(p_ini) != len(p_fin) or not p_ini:
        return [ini]
    if p_ini[:-1] != p_fin[:-1]:
        return [ini]
    padre = '.'.join(str(x) for x in p_ini[:-1])
    return [
        f"{padre}.{i}" if padre else str(i)
        for i in range(p_ini[-1], p_fin[-1] + 1)
    ]


def _prefijo_ancestro_comun(prefijos: list[str]) -> str:

    unicos = list({p for p in prefijos if p})
    if not unicos:
        return ""
    if len(unicos) == 1:
        return unicos[0]
    partes = [p.split('.') for p in unicos]
    prof_max = max(len(p) for p in partes)
    prof_min = min(len(p) for p in partes)
    for nivel in range(prof_min, 0, -1):
        candidatos = {'.'.join(p[:nivel]) for p in partes}
        if len(candidatos) == 1:
            if prof_max - nivel <= 2:
                return candidatos.pop()
            return ""
    return ""


def _es_subseccion(nombre: str, prefijo_padre: str) -> bool:
    """True si la sección pertenece al prefijo padre o es una subsección de él."""
    if not prefijo_padre:
        return False
    p = _extraer_prefijo(nombre)
    return p == prefijo_padre or p.startswith(prefijo_padre + ".")


CHUNK_SIZE    = 600
CHUNK_OVERLAP = 80
K_RESULTADOS  = 4
K_INICIAL     = 6
MAX_FRAGMENTOS_SECCION = 50

_MIN_CHARS_CHUNK = 80



def _encontrar_encabezado_en_texto(texto: str, nombre_seccion: str) -> int:
    """
    Localiza el encabezado de una sección en el texto de contenido de una página.

    Returns posición de inicio (0-indexed), o -1 si no se encuentra.
    Estrategia en cascada: búsqueda exacta → normalización de espacios → prefijo numérico al inicio de línea.
    """
    idx = texto.find(nombre_seccion)
    if idx >= 0:
        return idx

    nombre_norm = re.sub(r'\s+', ' ', nombre_seccion).strip()
    idx = texto.find(nombre_norm)
    if idx >= 0:
        return idx

    m_pref = re.match(r'^(\d[\d\.]*)', nombre_norm)
    if m_pref:
        prefix = m_pref.group(1).rstrip('.')
        pattern = r'(?:(?<=\n)|^)' + re.escape(prefix) + r'[.\s]'
        m = re.search(pattern, texto)
        if m:
            pos = m.start()
            return pos + (1 if pos < len(texto) and texto[pos] == '\n' else 0)

    return -1


def _agrupar_por_toc(
    paginas: list[tuple[int, str]],
    estructura_toc: dict[str, int],
) -> list[tuple[str, str, int]]:

    if not estructura_toc or not paginas:
        texto_total = "\n\n".join(t for _, t in sorted(paginas))
        return [("Documento completo", texto_total, 1)]

    secciones_ord = sorted(estructura_toc.items(), key=lambda x: x[1])
    acumulado: dict[str, list[str]] = {nombre: [] for nombre, _ in secciones_ord}
    paginas_asignadas = 0

    for pag, texto_pag in sorted(paginas):
        secciones_en_pag = [n for n, p in secciones_ord if p == pag]

        if not secciones_en_pag:
            running: str | None = None
            for nombre, pag_inicio in reversed(secciones_ord):
                if pag_inicio <= pag:
                    running = nombre
                    break
            if running is not None:
                acumulado[running].append(texto_pag)
                paginas_asignadas += 1
        else:
            prev: str | None = None
            for nombre, pag_inicio in reversed(secciones_ord):
                if pag_inicio < pag:
                    prev = nombre
                    break

            posiciones: dict[str, int] = {}
            for nombre in secciones_en_pag:
                pos = _encontrar_encabezado_en_texto(texto_pag, nombre)
                if pos >= 0:
                    posiciones[nombre] = pos

            if posiciones:
                secciones_pos = sorted(posiciones.items(), key=lambda x: x[1])
                primera_pos = secciones_pos[0][1]
                if primera_pos > 0 and prev is not None:
                    previo = texto_pag[:primera_pos].strip()
                    if previo:
                        acumulado[prev].append(previo)
                for i, (nombre, pos) in enumerate(secciones_pos):
                    sig = secciones_pos[i + 1][1] if i + 1 < len(secciones_pos) else len(texto_pag)
                    frag = texto_pag[pos:sig].strip()
                    if frag:
                        acumulado[nombre].append(frag)
            else:
                acumulado[secciones_en_pag[-1]].append(texto_pag)

            paginas_asignadas += 1

    if paginas_asignadas == 0:
        logger.warning(
            "TOC detectado pero ninguna página coincide con sus números de página. "
            "Fallback a chunking por tamaño fijo."
        )
        texto_total = "\n\n".join(t for _, t in sorted(paginas))
        return [("Documento completo", texto_total, 1)]

    grupos: list[tuple[str, str, int]] = []
    for nombre, pag_inicio in secciones_ord:
        texto_sec = "\n\n".join(acumulado[nombre])
        if texto_sec.strip():
            grupos.append((nombre, texto_sec.strip(), pag_inicio))

    logger.info(
        f"TOC: {len(grupos)} secciones con contenido "
        f"({paginas_asignadas}/{len(paginas)} páginas asignadas)"
    )
    return grupos


def _secciones_a_documentos(
    grupos: list[tuple[str, str, int]],
    collection_name: str,
    splitter: RecursiveCharacterTextSplitter,
) -> list[Document]:

    docs: list[Document] = []
    for nombre, texto, pag_inicio in grupos:
        texto_limpio = texto.strip()
        if len(texto_limpio) < _MIN_CHARS_CHUNK:
            logger.debug(
                f"Sección '{nombre}' descartada del índice ({len(texto_limpio)} chars — solo título)"
            )
            continue

        metadata = {
            "source":        collection_name,
            "tipo":          "proyecto_tesis",
            "seccion":       nombre,
            "pagina_inicio": pag_inicio,
        }

        if len(texto_limpio) <= CHUNK_SIZE:
            docs.append(Document(page_content=texto_limpio, metadata=metadata))
        else:
            chunks = splitter.create_documents([texto_limpio], metadatas=[metadata])
            docs.extend(chunks)

    return docs


_STOP_WORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una", "y", "e", "o", "u",
    "con", "en", "al", "para", "por", "que", "se", "su", "sus", "es", "son",
    "a", "ante", "bajo", "desde", "sin", "sobre", "tras", "como",
}


def _palabras_clave(texto: str) -> set[str]:
    """Extrae palabras significativas (sin números, puntuación ni stop words)."""
    tokens = re.sub(r'[\d\.\,\-–\(\)\[\]/]', ' ', texto.lower()).split()
    return {t for t in tokens if len(t) > 2 and t not in _STOP_WORDS}


def _buscar_query_semantica(seccion: str) -> str:

    for sec in SECCIONES_TESIS:
        if sec["nombre"] == seccion:
            return sec["query"]

    # Resolver por la sección de rúbrica que GOBIERNA esta (prefijo + semántica
    # fuerte). Evita que palabras genéricas ("estudio") elijan la query equivocada
    # (p. ej. '4.3 Diseño del estudio' → query de '1.3 Importancia del estudio').
    key = _seccion_rubrica_para(seccion)
    if key:
        for sec in SECCIONES_TESIS:
            if sec["nombre"] == key:
                return sec["query"]

    kw_seccion = _palabras_clave(seccion)
    if kw_seccion:
        mejor_score = 0
        mejor_query: str | None = None
        for sec in SECCIONES_TESIS:
            score = len(kw_seccion & _palabras_clave(sec["nombre"]))
            if score > mejor_score:
                mejor_score = score
                mejor_query = sec["query"]
        if mejor_score >= 1 and mejor_query:
            return mejor_query

    prefijo = _extraer_prefijo(seccion)
    if prefijo:
        for sec in SECCIONES_TESIS:
            p = _extraer_prefijo(sec["nombre"])
            if p and p == prefijo:
                return sec["query"]

    return seccion



def construir_vector_store(
    paginas: list[tuple[int, str]],
    estructura_toc: dict[str, int],
    embeddings: HuggingFaceEmbeddings,
    collection_name: str = "tesis_upao",
) -> Chroma:

    if not paginas:
        raise ValueError("El texto extraído del PDF está vacío.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", "   ", " ", ""],
    )

    if estructura_toc:
        grupos = _agrupar_por_toc(paginas, estructura_toc)
        documentos = _secciones_a_documentos(grupos, collection_name, splitter)
        n_secciones = len(grupos)
        logger.info(
            f"Chunking por TOC: {n_secciones} secciones → {len(documentos)} fragmentos"
        )
    else:
        texto_total = "\n\n".join(t for _, t in sorted(paginas))
        documentos = splitter.create_documents(
            [texto_total],
            metadatas=[{"source": collection_name, "tipo": "proyecto_tesis"}],
        )
        logger.info(f"Chunking fijo (sin TOC): {len(documentos)} fragmentos")

    logger.info(f"Tesis dividida en {len(documentos)} fragmentos")

    for idx, doc in enumerate(documentos):
        doc.metadata["chunk_index"] = idx

    cliente = chromadb.EphemeralClient()
    store = Chroma(
        client=cliente,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
    store.add_documents(documentos)

    n = store._collection.count()
    logger.info(f"ChromaDB tesis listo: {n} fragmentos en '{collection_name}'")
    return store


def limpiar_marcas_rag(texto: str) -> str:
    """Quita los marcadores que añade el RAG ('[Fragmento N]', separadores '---')
    para que nunca lleguen al chat ni al texto que ve/echo el LLM."""
    import re as _re
    t = _re.sub(r"\[Fragmento\s*\d+\]", "", texto or "")
    t = _re.sub(r"\n\s*-{3,}\s*\n", "\n\n", t)
    return _re.sub(r"\n{3,}", "\n\n", t).strip()


def recuperar_contexto(
    vector_store: Chroma,
    seccion: str,
    k: int = K_RESULTADOS,
) -> str:

    from collections import Counter

    query = _buscar_query_semantica(seccion)
    logger.info(f"RAG tesis → '{seccion}' | query: '{query[:55]}…'")

    try:
        n_total = vector_store._collection.count()
        todos_docs = vector_store.similarity_search(query, k=n_total)
    except Exception as exc:
        logger.error(f"Error en similarity_search tesis: {exc}")
        return f"[Error en búsqueda RAG: {exc}]"

    if not todos_docs:
        return (
            f"No se encontró contenido relevante en el PDF para '{seccion}'.\n"
            "El estudiante puede no haber redactado aún esta sección."
        )

    # Secciones SIN prefijo numérico (p. ej. la carátula sintética "Título del
    # proyecto"): traer SOLO sus propios chunks, sin expandir a un capítulo entero.
    if not _extraer_prefijo(seccion):
        propios = [d for d in todos_docs if d.metadata.get("seccion") == seccion]
        if propios:
            propios.sort(key=lambda d: d.metadata.get("chunk_index", 0))
            propios = propios[:MAX_FRAGMENTOS_SECCION]
            fragmentos = [f"[Fragmento {i + 1}]\n{d.page_content}" for i, d in enumerate(propios)]
            logger.info(
                f"RAG tesis: sección sin prefijo '{seccion}' → "
                f"{len(propios)} fragmentos propios (sin expandir a capítulo)"
            )
            return "\n\n" + "\n\n---\n\n".join(fragmentos) + "\n"

    top_meta = [d.metadata.get("seccion") for d in todos_docs[:K_INICIAL]
                if d.metadata.get("seccion")]

    if not top_meta:
        docs = todos_docs[:k]
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
        logger.info(f"RAG tesis: {len(docs)} fragmentos (sin metadata de sección)")
    else:
        # Anclar a la unidad de la rúbrica: para una hoja del TOC ('1.2.1 Objetivo
        # general') esto devuelve el prefijo padre ('1.2') para que la sección
        # hermana ('1.2.2 Objetivos específicos') entre en el mismo contexto.
        config_prefijos = prefijos_evaluacion_para_seccion(seccion) or _extraer_prefijos_rango(seccion)
        docs_config = [
            d for d in todos_docs
            if any(_es_subseccion(d.metadata.get("seccion", ""), cp) for cp in config_prefijos)
        ] if config_prefijos else []

        if docs_config:
            # El prefijo numérico de la sección es AUTORITATIVO: usa sus propios chunks
            # aunque la similitud rankee más alto otra sección parecida (corrige p. ej.
            # 'Antecedentes' → 'Referencias', que comparten vocabulario de autores/citas).
            docs = sorted(docs_config, key=lambda d: d.metadata.get("chunk_index", 0))[:MAX_FRAGMENTOS_SECCION]
            logger.info(
                f"RAG tesis: prefijos config {config_prefijos} → "
                f"{len(docs)} fragmentos (anclado por prefijo)"
            )
        else:
            top_prefijos = [_extraer_prefijo(s) for s in top_meta if _extraer_prefijo(s)]
            ancestor = _prefijo_ancestro_comun(top_prefijos)
            if ancestor:
                docs = [d for d in todos_docs
                        if _es_subseccion(d.metadata.get("seccion", ""), ancestor)]
                docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
                docs = docs[:MAX_FRAGMENTOS_SECCION]
                logger.info(
                    f"RAG tesis: ancestro semántico '{ancestor}' "
                    f"(top prefijos: {sorted(set(top_prefijos))[:6]}) → "
                    f"{len(docs)} fragmentos"
                )
            else:
                seccion_dominante = Counter(top_meta).most_common(1)[0][0]
                prefijo_dom = _extraer_prefijo(seccion_dominante)
                if prefijo_dom:
                    docs = [d for d in todos_docs
                            if _es_subseccion(d.metadata.get("seccion", ""), prefijo_dom)]
                else:
                    docs = [d for d in todos_docs
                            if d.metadata.get("seccion") == seccion_dominante]
                docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
                docs = docs[:MAX_FRAGMENTOS_SECCION]
                logger.info(
                    f"RAG tesis: dominante '{seccion_dominante}' → "
                    f"{len(docs)} fragmentos"
                )

    fragmentos = [f"[Fragmento {i + 1}]\n{d.page_content}" for i, d in enumerate(docs)]
    resultado = "\n\n" + "\n\n---\n\n".join(fragmentos) + "\n"
    logger.info(f"RAG tesis: {len(resultado)} chars totales recuperados")
    return resultado


def resolver_seccion_semantica(
    vector_store: Chroma,
    concepto: str,
    toc_nombres: list[str] | None = None,
    k: int = 6,
) -> str | None:
    """Ubica vía RAG la sección del TOC que CONTIENE un sub-concepto.

    Útil cuando el estudiante pide evaluar algo que no es un título exacto del
    índice (p. ej. 'operacionalización de variables', 'variable dependiente'),
    porque ese contenido vive DENTRO de una sección mayor ('3.2 Variables') y
    no aparece tal cual en el TOC. Devuelve el nombre de la sección dominante
    entre los fragmentos más similares, o None si no hay coincidencia.
    """
    if not concepto or vector_store is None:
        return None
    try:
        docs = vector_store.similarity_search(concepto, k=k)
    except Exception as exc:
        logger.warning(f"[resolver_seccion] Error RAG para '{concepto}': {exc}")
        return None

    from collections import Counter

    secs = [d.metadata.get("seccion") for d in docs if d.metadata.get("seccion")]
    if not secs:
        return None
    for sec, _freq in Counter(secs).most_common():
        if not toc_nombres or sec in toc_nombres:
            logger.info(f"[resolver_seccion] '{concepto}' → '{sec}'")
            return sec
    return None


def recuperar_con_vecinos(
    vector_store: Chroma,
    consulta: str,
    seccion: str | None = None,
    k: int = 5,
    ventana: int = 1,
    max_chunks: int = 14,
) -> str:
    """Top-k por similitud + expansión de vecinos ±`ventana` de la MISMA sección.

    Reensambla oraciones cortadas entre fragmentos: por cada chunk relevante trae
    también el anterior y el siguiente (en orden de lectura, vía `chunk_index`
    global). Así una pregunta de formulación partida entre dos chunks no se da por
    ausente. Si se indica `seccion`, restringe la búsqueda a esa sección (o sus
    subsecciones). Acota el total a `max_chunks` para no inflar el prompt.

    Devuelve el texto con marcadores `[Fragmento N]`; usa `limpiar_marcas_rag`
    si necesitas el texto crudo.
    """
    if vector_store is None or not (consulta or "").strip():
        return ""

    try:
        hits = vector_store.similarity_search(consulta, k=max(k, 1))
    except Exception as exc:
        logger.warning(f"[vecinos] similarity_search falló: {exc}")
        return ""
    if not hits:
        return ""

    if seccion:
        pref = _extraer_prefijo(seccion)
        filtrados = [
            d for d in hits
            if d.metadata.get("seccion") == seccion
            or (pref and _es_subseccion(d.metadata.get("seccion", ""), pref))
        ]
        if filtrados:
            hits = filtrados

    # Índice completo del documento: chunk_index es global y refleja el orden de
    # lectura, así que (sección, índice±1) es el fragmento contiguo de la misma sección.
    try:
        bruto = vector_store._collection.get(include=["documents", "metadatas"])
        documentos = bruto.get("documents") or []
        metadatas = bruto.get("metadatas") or []
    except Exception as exc:
        logger.warning(f"[vecinos] get() falló: {exc}")
        documentos, metadatas = [], []

    por_idx: dict[int, tuple[str, str]] = {}
    for texto, meta in zip(documentos, metadatas):
        ci = meta.get("chunk_index")
        if ci is not None:
            por_idx[ci] = (meta.get("seccion", ""), texto)

    seleccion: set[int] = set()
    for d in hits:
        ci = d.metadata.get("chunk_index")
        sec = d.metadata.get("seccion", "")
        if ci is None:
            continue
        seleccion.add(ci)
        for off in range(1, ventana + 1):
            for vecino in (ci - off, ci + off):
                if vecino in por_idx and por_idx[vecino][0] == sec:
                    seleccion.add(vecino)

    if not seleccion:
        # Sin chunk_index utilizable: devolver los propios hits en orden de aparición.
        docs = hits[:max_chunks]
        return "\n\n---\n\n".join(
            f"[Fragmento {i + 1}]\n{d.page_content}" for i, d in enumerate(docs)
        )

    ordenados = sorted(seleccion)[:max_chunks]
    partes = []
    for i, ci in enumerate(ordenados):
        sec, texto = por_idx.get(ci, ("", ""))
        etiqueta = f"[Fragmento {i + 1}" + (f" · {sec}]" if sec else "]")
        partes.append(f"{etiqueta}\n{texto}")
    logger.info(
        f"[vecinos] '{consulta[:40]}…' → {len(ordenados)} fragmentos "
        f"(de {len(hits)} hits, ventana ±{ventana})"
    )
    return "\n\n---\n\n".join(partes)


_CONSULTAS_CRUZADAS: dict[str, str] = {
    "Título y delimitación":  "título investigación variables independiente dependiente espacio tiempo",
    "Problema central":       "problema central formulación pregunta investigación planteamiento realidad",
    "Objetivos":              "objetivo general específicos investigación derivan problema",
    "Hipótesis":              "hipótesis relación variables supuesto básico específicas",
    "Operacionalización":     "operacionalización variables dimensiones indicadores escala medición",
    "Marco metodológico":     "tipo método diseño investigación cuantitativo cualitativo",
    "Antecedentes / Marco teórico": "antecedentes investigaciones previas base teórica conceptos",
}

_MAX_CHARS_POR_FRAGMENTO = 3000
_MAX_CHARS_CRUZADO       = 15_000
_N_SECCIONES_POR_QUERY   = 2


def recuperar_contexto_cruzado(
    vector_store: Chroma,
    seccion_principal: str,
) -> str:
    """
    Recupera secciones RELACIONADAS (no la propia unidad de evaluación) para que
    los agentes detecten incoherencias contra el resto del proyecto.

    Diferencias clave respecto a recuperar_contexto:
      - Excluye toda la UNIDAD de evaluación (prefijo de rúbrica, no solo la hoja),
        porque esa unidad ya viaja en el contexto principal.
      - Cada consulta cruzada aporta hasta `_N_SECCIONES_POR_QUERY` secciones
        distintas (no una sola), de modo que un tema repartido en hermanas
        (p.ej. metodología en 4.1/4.2/4.3/4.5/4.7) no quede representado por una
        sola rebanada.
      - De cada sección elegida se traen TODOS sus chunks en orden de lectura.
    """
    prefijos_excluidos = [
        p for p in (prefijos_evaluacion_para_seccion(seccion_principal)
                    or [_extraer_prefijo(seccion_principal)])
        if p
    ]

    try:
        n_total = vector_store._collection.count()
    except Exception:
        n_total = 0

    partes: list[str] = []
    prefijos_visitados: set[str] = set()
    chars_acumulados = 0

    for nombre_consulta, query in _CONSULTAS_CRUZADAS.items():
        if chars_acumulados >= _MAX_CHARS_CRUZADO:
            break
        try:
            docs = vector_store.similarity_search(query, k=8)
        except Exception as exc:
            logger.warning(f"[Cross-context] Error en query '{nombre_consulta}': {exc}")
            continue

        tomadas = 0
        for doc in docs:
            if tomadas >= _N_SECCIONES_POR_QUERY or chars_acumulados >= _MAX_CHARS_CRUZADO:
                break

            seccion_doc = doc.metadata.get("seccion", "")
            prefijo_doc = _extraer_prefijo(seccion_doc)
            if not seccion_doc or not prefijo_doc:
                continue
            if any(_es_subseccion(seccion_doc, pe) for pe in prefijos_excluidos):
                continue
            if prefijo_doc in prefijos_visitados:
                continue
            if len(doc.page_content.strip()) < _MIN_CHARS_CHUNK:
                logger.debug(
                    f"[Cross-context] '{seccion_doc}' omitida en recuperación "
                    f"({len(doc.page_content.strip())} chars — solo título)"
                )
                continue

            try:
                if n_total:
                    todos_sec_docs = vector_store.similarity_search(seccion_doc, k=n_total)
                    sec_chunks = [d for d in todos_sec_docs if d.metadata.get("seccion") == seccion_doc]
                    sec_chunks.sort(key=lambda d: d.metadata.get("chunk_index", 0))
                    sec_chunks = sec_chunks[:6]
                else:
                    sec_chunks = [doc]
            except Exception:
                sec_chunks = [doc]

            texto_seccion = "\n".join(c.page_content for c in sec_chunks)
            fragmento = texto_seccion[:_MAX_CHARS_POR_FRAGMENTO]
            partes.append(f"**{seccion_doc}**\n{fragmento}")
            prefijos_visitados.add(prefijo_doc)
            chars_acumulados += len(fragmento)
            tomadas += 1

    if not partes:
        return ""

    resultado = "\n\n---\n\n".join(partes)
    logger.info(
        f"[Cross-context] {len(partes)} secciones cruzadas recuperadas "
        f"({chars_acumulados} chars) | excluidos prefijos {prefijos_excluidos}"
    )
    return resultado


def recuperar_vista_general(vector_store: Chroma) -> str:

    try:
        result = vector_store._collection.get(include=["metadatas", "documents"])
        metadatas = result.get("metadatas") or []
        documents = result.get("documents") or []

        por_capitulo: dict[str, list[tuple[str, str]]] = {}
        for meta, doc in zip(metadatas, documents):
            seccion = meta.get("seccion", "")
            m = re.match(r'^(\d)', seccion.strip())
            capitulo = m.group(1) if m else "?"
            por_capitulo.setdefault(capitulo, []).append((seccion, doc))

        partes: list[str] = []
        for cap in sorted(por_capitulo.keys()):
            secciones_cap = por_capitulo[cap]
            mejor_seccion, mejor_doc = max(secciones_cap, key=lambda x: len(x[1]))
            extracto = mejor_doc[:600]
            partes.append(f"**{mejor_seccion}**\n{extracto}")

        if not partes:
            return ""

        resultado = "\n\n---\n\n".join(partes)
        logger.info(f"[Vista general] {len(partes)} capítulos representados ({len(resultado)} chars)")
        return resultado

    except Exception as exc:
        logger.error(f"Error en recuperar_vista_general: {exc}")
        return ""


def obtener_stats_secciones(vector_store: Chroma) -> list[dict]:

    try:
        result = vector_store._collection.get(include=["metadatas", "documents"])
        metadatas = result.get("metadatas") or []
        documents = result.get("documents") or []

        stats: dict[str, dict] = {}
        for meta, doc in zip(metadatas, documents):
            seccion = meta.get("seccion", "Sin sección")
            pag     = meta.get("pagina_inicio", 0)
            chars   = len(doc)
            if seccion not in stats:
                stats[seccion] = {
                    "seccion":       seccion,
                    "pagina_inicio": pag,
                    "chars":         0,
                    "n_fragmentos":  0,
                }
            stats[seccion]["chars"]        += chars
            stats[seccion]["n_fragmentos"] += 1

        return sorted(stats.values(), key=lambda x: x["pagina_inicio"])
    except Exception as exc:
        logger.error(f"Error obteniendo stats de secciones: {exc}")
        return []
