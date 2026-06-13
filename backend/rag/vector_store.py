

import io
import os
import re
import logging
from typing import List, Optional

import pdfplumber
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from backend.config import SECCIONES_TESIS, LIBRARY_CHROMA_PATH, BOOKS_PRELOAD_DIR

logger = logging.getLogger(__name__)

MODELO_EMBEDDING = "sentence-transformers/all-MiniLM-L6-v2"

_RE_LINEA_INDICE = re.compile(r'\.{4,}\s*\d{1,4}\s*$')

def _es_chunk_indice(texto: str) -> bool:

    lineas = [l for l in texto.split('\n') if l.strip()]
    if not lineas:
        return False
    lineas_indice = sum(1 for l in lineas if _RE_LINEA_INDICE.search(l.strip()))
    return lineas_indice / len(lineas) >= 0.35
CHUNK_SIZE       = 600
CHUNK_OVERLAP    = 80
K_RESULTADOS     = 4



def extraer_texto_pdf(pdf_bytes: bytes) -> str:

    paginas = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto_pagina = pagina.extract_text()
                if texto_pagina and texto_pagina.strip():
                    paginas.append(texto_pagina.strip())
                    logger.debug(f"  Pág. {i+1}: {len(texto_pagina)} chars")
    except Exception as exc:
        logger.error(f"Error extrayendo texto del PDF: {exc}")
        raise

    texto_completo = "\n\n".join(paginas)
    logger.info(f"PDF extraído: {len(paginas)} páginas con texto, {len(texto_completo)} caracteres totales")
    return texto_completo



def construir_vector_store(
    texto: str,
    embeddings: HuggingFaceEmbeddings,
    collection_name: str = "tesis_upao",
) -> Chroma:

    if not texto.strip():
        raise ValueError("El texto extraído del PDF está vacío.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", "   ", " ", ""],
    )
    documentos = splitter.create_documents(
        [texto],
        metadatas=[{"source": collection_name, "tipo": "proyecto_tesis"}],
    )
    antes = len(documentos)
    documentos = [d for d in documentos if not _es_chunk_indice(d.page_content)]
    logger.info(
        f"Texto dividido: {antes} fragmentos totales → {len(documentos)} útiles "
        f"({antes - len(documentos)} chunks de índice/TOC filtrados)"
    )

    cliente_chroma = chromadb.EphemeralClient()

    vector_store = Chroma(
        client=cliente_chroma,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
    vector_store.add_documents(documentos)

    n_indexados = vector_store._collection.count()
    logger.info(f"ChromaDB listo: {n_indexados} fragmentos indexados en '{collection_name}'")
    return vector_store


def recuperar_contexto(
    vector_store: Chroma,
    seccion: str,
    k: int = K_RESULTADOS,
) -> str:

    query = seccion
    for sec_cfg in SECCIONES_TESIS:
        if sec_cfg["nombre"] == seccion:
            query = sec_cfg["query"]
            break

    logger.info(f"RAG search → sección: '{seccion}' | query: '{query[:60]}...'")

    try:
        docs = vector_store.similarity_search(query, k=k)
    except Exception as exc:
        logger.error(f"Error en similarity_search: {exc}")
        return f"[Error en búsqueda RAG: {exc}]"

    if not docs:
        return (
            f"No se encontró contenido relevante en el PDF para la sección: '{seccion}'.\n"
            "El estudiante puede no haber redactado aún esta sección."
        )

    fragmentos = [f"[Fragmento {i+1}]\n{d.page_content}" for i, d in enumerate(docs)]
    resultado = "\n\n" + "\n\n---\n\n".join(fragmentos) + "\n"
    logger.info(f"RAG recuperó {len(docs)} fragmentos ({len(resultado)} chars)")
    return resultado


def cargar_modelo_embeddings() -> HuggingFaceEmbeddings:

    logger.info(f"Cargando modelo de embeddings: {MODELO_EMBEDDING}")
    return HuggingFaceEmbeddings(
        model_name=MODELO_EMBEDDING,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

_BIBLIOTECA_COLLECTION = "biblioteca_metodologia"
_CHUNK_LIBRO   = 800
_OVERLAP_LIBRO = 100
_K_LIBROS      = 3


def cargar_o_crear_biblioteca(embeddings: HuggingFaceEmbeddings) -> Chroma:
    """
    Carga la biblioteca persistente existente o crea una nueva vacía.
    Usa PersistentClient → los datos se guardan en LIBRARY_CHROMA_PATH (disco).

    Llamar con @st.cache_resource para compartir la instancia entre reruns.
    """
    os.makedirs(LIBRARY_CHROMA_PATH, exist_ok=True)
    cliente = chromadb.PersistentClient(path=LIBRARY_CHROMA_PATH)
    vs = Chroma(
        client=cliente,
        collection_name=_BIBLIOTECA_COLLECTION,
        embedding_function=embeddings,
    )
    n = vs._collection.count()
    logger.info(f"Biblioteca cargada: {n} fragmentos en '{LIBRARY_CHROMA_PATH}'")
    return vs


def agregar_libro(
    vs_libros: Chroma,
    pdf_bytes: bytes,
    nombre_libro: str,
) -> int:

    texto = extraer_texto_pdf(pdf_bytes)
    if not texto.strip():
        raise ValueError(f"El PDF '{nombre_libro}' está vacío o no tiene texto seleccionable.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_LIBRO,
        chunk_overlap=_OVERLAP_LIBRO,
        separators=["\n\n", "\n", ". ", "   ", " ", ""],
    )
    docs = splitter.create_documents(
        [texto],
        metadatas=[{"fuente": nombre_libro, "tipo": "libro_metodologia"}],
    )
    vs_libros.add_documents(docs)
    logger.info(f"Libro '{nombre_libro}' indexado: {len(docs)} fragmentos")
    return len(docs)


def precargar_libros_desde_carpeta(
    vs_libros: Chroma,
    libros_ya_cargados: List[str],
) -> List[str]:

    if not os.path.isdir(BOOKS_PRELOAD_DIR):
        os.makedirs(BOOKS_PRELOAD_DIR, exist_ok=True)
        return []

    nuevos = []
    for archivo in sorted(os.listdir(BOOKS_PRELOAD_DIR)):
        if not archivo.lower().endswith(".pdf"):
            continue
        nombre = os.path.splitext(archivo)[0]
        if nombre in libros_ya_cargados:
            logger.info(f"Libro '{nombre}' ya indexado, omitiendo.")
            continue
        ruta = os.path.join(BOOKS_PRELOAD_DIR, archivo)
        with open(ruta, "rb") as f:
            pdf_bytes = f.read()
        try:
            n = agregar_libro(vs_libros, pdf_bytes, nombre)
            nuevos.append(nombre)
            logger.info(f"Pre-cargado: '{nombre}' ({n} fragmentos)")
        except Exception as exc:
            logger.warning(f"No se pudo pre-cargar '{nombre}': {exc}")
    return nuevos


def recuperar_contexto_teorico(
    vs_libros: Chroma,
    seccion: str,
    k: int = _K_LIBROS,
) -> str:

    try:
        n_total = vs_libros._collection.count()
        if n_total == 0:
            return ""

        query_base = seccion
        for sec_cfg in SECCIONES_TESIS:
            if sec_cfg["nombre"] == seccion:
                query_base = sec_cfg["query"]
                break
        query = f"metodología investigación {query_base}"

        docs = vs_libros.similarity_search(query, k=min(k, n_total))
        if not docs:
            return ""

        partes = []
        for doc in docs:
            fuente = doc.metadata.get("fuente", "Fuente desconocida")
            partes.append(f"[Fuente: {fuente}]\n{doc.page_content}")

        resultado = "\n\n---\n\n".join(partes)
        logger.info(f"Biblioteca: {len(docs)} fragmentos recuperados para '{seccion}'")
        return resultado

    except Exception as exc:
        logger.warning(f"Error recuperando contexto teórico: {exc}")
        return ""


def listar_libros(vs_libros: Chroma) -> List[dict]:
    """
    Lista los libros únicos en la biblioteca con su número de fragmentos.

    Returns:
        Lista de dicts: [{"nombre": str, "fragmentos": int}, ...]
    """
    try:
        resultado = vs_libros._collection.get(include=["metadatas"])
        conteo: dict = {}
        for meta in (resultado.get("metadatas") or []):
            if meta and "fuente" in meta:
                nombre = meta["fuente"]
                conteo[nombre] = conteo.get(nombre, 0) + 1
        return [{"nombre": k, "fragmentos": v} for k, v in sorted(conteo.items())]
    except Exception as exc:
        logger.warning(f"Error listando libros: {exc}")
        return []


def eliminar_libro(vs_libros: Chroma, nombre_libro: str) -> int:

    try:
        coleccion = vs_libros._collection
        resultados = coleccion.get(
            where={"fuente": nombre_libro},
            include=["metadatas"],
        )
        ids = resultados.get("ids", [])
        if ids:
            coleccion.delete(ids=ids)
            logger.info(f"Eliminado '{nombre_libro}': {len(ids)} fragmentos")
        return len(ids)
    except Exception as exc:
        logger.error(f"Error eliminando '{nombre_libro}': {exc}")
        return 0
