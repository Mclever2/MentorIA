"""Extracción de texto desde archivos PDF usando pdfplumber."""

import io
import re
import logging
import warnings
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

_RE_LINEA_TOC = re.compile(r'\.{4,}\s*\d{1,4}\s*$')
_RE_ENTRADA_TOC = re.compile(
    r'^(\d[\d\.\-–]*\.?\s*[A-ZÁÉÍÓÚÜÑ][^\.]{3,}?)\s*\.{3,}\s*(\d{1,4})\s*$',
    re.IGNORECASE,
)
_UMBRAL_PAGINA_TOC = 0.28


def _ratio_lineas_toc(texto_pagina: str) -> float:
    """Retorna la fracción de líneas no vacías que tienen patrón de índice."""
    lineas = [l.strip() for l in texto_pagina.split('\n') if l.strip()]
    if len(lineas) < 2:
        return 0.0
    n_toc = sum(1 for l in lineas if _RE_LINEA_TOC.search(l))
    return n_toc / len(lineas)


def _parsear_toc(paginas_toc: list[str]) -> dict[str, int]:
    """
    Extrae la estructura del índice: {nombre_seccion: numero_pagina}.
    Solo captura entradas que empiezan con número (secciones numeradas).
    """
    estructura: dict[str, int] = {}
    for texto in paginas_toc:
        for linea in texto.split('\n'):
            m = _RE_ENTRADA_TOC.match(linea.strip())
            if m:
                nombre = re.sub(r'\s+', ' ', m.group(1)).strip()
                try:
                    pagina = int(m.group(2))
                    estructura[nombre] = pagina
                except ValueError:
                    pass
    return estructura


def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrae el texto completo de un PDF (incluyendo páginas de índice)."""
    paginas = []
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Cannot set.*color")
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for i, pagina in enumerate(pdf.pages):
                    texto = pagina.extract_text()
                    if texto and texto.strip():
                        paginas.append(texto.strip())
                        logger.debug(f"  Pág. {i + 1}: {len(texto)} chars")
    except Exception as exc:
        logger.error(f"Error extrayendo texto del PDF: {exc}")
        raise

    resultado = "\n\n".join(paginas)
    logger.info(
        f"PDF extraído: {len(paginas)} páginas con texto, "
        f"{len(resultado):,} caracteres totales"
    )
    return resultado


def extraer_contenido_sin_indice(
    pdf_bytes: bytes,
) -> tuple[list[tuple[int, str]], dict[str, int]]:
    """
    Extrae el texto del PDF separando contenido real de páginas de índice/TOC.

    Estrategia:
      1. Analiza cada página por separado.
      2. Las páginas donde ≥28 % de líneas tienen patrón "texto......N"
         se clasifican como TOC y se usan para parsear la estructura.
      3. Las páginas de contenido se retornan como lista (numero_pagina, texto).

    Returns:
        paginas_contenido: lista de (numero_pagina_1indexed, texto_pagina).
        estructura_toc:    dict {nombre_sección → numero_pagina_inicio}.
    """
    paginas_contenido: list[tuple[int, str]] = []
    paginas_toc_texto: list[str] = []
    n_toc = 0

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Cannot set.*color")
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total = len(pdf.pages)
                for i, pagina in enumerate(pdf.pages):
                    numero_pagina = i + 1
                    texto = pagina.extract_text()
                    if not texto or not texto.strip():
                        continue

                    ratio = _ratio_lineas_toc(texto)

                    if ratio >= _UMBRAL_PAGINA_TOC:
                        n_toc += 1
                        paginas_toc_texto.append(texto)
                        logger.info(
                            f"Pág. {numero_pagina}/{total}: ÍNDICE (ratio={ratio:.2f}) — excluida del RAG"
                        )
                    else:
                        paginas_contenido.append((numero_pagina, texto.strip()))

    except Exception as exc:
        logger.error(f"Error extrayendo contenido sin índice: {exc}")
        raise

    estructura_toc = _parsear_toc(paginas_toc_texto)

    logger.info(
        f"Extracción inteligente: {len(paginas_contenido)} páginas de contenido, "
        f"{n_toc} páginas de índice omitidas, "
        f"{len(estructura_toc)} secciones detectadas en TOC"
    )
    if estructura_toc:
        secciones_str = ', '.join(list(estructura_toc.keys())[:6])
        logger.info(f"Estructura TOC: {secciones_str}{'…' if len(estructura_toc) > 6 else ''}")

    return paginas_contenido, estructura_toc
