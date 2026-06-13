

import os
import logging
from typing import List

import chromadb
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import LIBRARY_CHROMA_PATH, BOOKS_PRELOAD_DIR, SECCIONES_TESIS
from .extractor import extraer_contenido_sin_indice

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "biblioteca_metodologia_e5"
_CHUNK_LIBRO     = 800
_OVERLAP_LIBRO   = 100
_K_LIBROS        = 10



def cargar_o_crear_biblioteca(embeddings: HuggingFaceEmbeddings) -> Chroma:

    os.makedirs(LIBRARY_CHROMA_PATH, exist_ok=True)
    cliente = chromadb.PersistentClient(path=LIBRARY_CHROMA_PATH)
    store = Chroma(
        client=cliente,
        collection_name=_COLLECTION_NAME,
        embedding_function=embeddings,
    )
    n = store._collection.count()
    logger.info(f"Biblioteca cargada: {n} fragmentos en '{LIBRARY_CHROMA_PATH}'")
    return store



def agregar_libro(
    vs_libros: Chroma,
    pdf_bytes: bytes,
    nombre_libro: str,
) -> int:

    paginas_contenido, _ = extraer_contenido_sin_indice(pdf_bytes)
    if not paginas_contenido:
        raise ValueError(f"El PDF '{nombre_libro}' está vacío o no tiene texto seleccionable.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_LIBRO,
        chunk_overlap=_OVERLAP_LIBRO,
        separators=["\n\n", "\n", ". ", "   ", " ", ""],
    )
    textos = [texto for _, texto in paginas_contenido]
    metadatas = [{"fuente": nombre_libro, "tipo": "libro_metodologia"} for _ in paginas_contenido]
    docs = splitter.create_documents(textos, metadatas=metadatas)
    vs_libros.add_documents(docs)
    logger.info(f"Libro '{nombre_libro}' indexado: {len(docs)} fragmentos")
    return len(docs)


def listar_libros(vs_libros: Chroma) -> List[dict]:

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
        col = vs_libros._collection
        res = col.get(where={"fuente": nombre_libro}, include=["metadatas"])
        ids = res.get("ids", [])
        if ids:
            col.delete(ids=ids)
            logger.info(f"Eliminado '{nombre_libro}': {len(ids)} fragmentos")
        return len(ids)
    except Exception as exc:
        logger.error(f"Error eliminando '{nombre_libro}': {exc}")
        return 0



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
        for sec in SECCIONES_TESIS:
            if sec["nombre"] == seccion:
                query_base = sec["query"]
                break
        query = f"metodología investigación {query_base}"

        docs = vs_libros.similarity_search(query, k=min(k, n_total))
        if not docs:
            return ""

        partes = [
            f"[Fuente: {d.metadata.get('fuente', 'Fuente desconocida')}]\n{d.page_content}"
            for d in docs
        ]
        resultado = "\n\n---\n\n".join(partes)
        logger.info(f"Biblioteca: {len(docs)} fragmentos para '{seccion}'")
        return resultado

    except Exception as exc:
        logger.warning(f"Error recuperando contexto teórico: {exc}")
        return ""
