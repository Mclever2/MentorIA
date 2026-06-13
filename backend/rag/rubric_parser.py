
import re
import io
import logging
from typing import Optional, List

import pdfplumber

logger = logging.getLogger(__name__)


def parse_rubrica_pdf(pdf_bytes: bytes) -> Optional[dict]:

    try:
        texto = _extraer_texto(pdf_bytes)
        items = _extraer_items_tabla(pdf_bytes)

        if len(items) < 3:
            logger.info("Extracción por tabla insuficiente, usando parseo por texto.")
            items = _extraer_items_texto(texto)

        if not items:
            logger.warning("No se encontraron ítems en el PDF de rúbrica.")
            return None

        secciones   = _agrupar_por_seccion(items)
        escala      = _extraer_escala(texto)
        vigesimal   = _extraer_vigesimal(texto)
        puntaje_max = len(items) * max(escala.keys(), default=3)

        logger.info(
            f"Rúbrica parseada: {len(items)} ítems, "
            f"{len(secciones)} secciones, puntaje_max={puntaje_max}"
        )

        return {
            "items":           items,
            "secciones":       secciones,
            "escala":          escala,
            "tabla_vigesimal": vigesimal,
            "total_items":     len(items),
            "puntaje_maximo":  puntaje_max,
            "texto_raw":       texto[:4000],
        }

    except Exception as exc:
        logger.error(f"Error parseando rúbrica PDF: {exc}")
        return None



def _extraer_texto(pdf_bytes: bytes) -> str:
    paginas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                paginas.append(t)
    return "\n\n".join(paginas)



def _extraer_items_tabla(pdf_bytes: bytes) -> List[dict]:
    """Extrae ítems usando detección de tablas de pdfplumber."""
    items: List[dict] = []
    current_seccion = "General"

    SKIP_KEYWORDS = {"ITEM", "ÍTEMS", "N°", "PUNTAJE", "NOTA", "TOTAL",
                     "SUB", "TABLA", "OBSERV", "ESCALA", "VALOR"}

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            tables = pagina.extract_tables() or []
            for table in tables:
                for row in table:
                    if not row:
                        continue

                    cells  = [str(c or "").strip() for c in row]
                    cell0  = cells[0] if cells else ""
                    cell1  = cells[1] if len(cells) > 1 else ""

                    if re.match(r"^\d{1,2}$", cell0) and len(cell1) > 5:
                        desc = cell1.replace("\n", " ").strip()
                        desc = re.sub(r"\s+[xX]\s*$", "", desc).strip()
                        items.append({
                            "numero":     int(cell0),
                            "descripcion": desc,
                            "seccion":    current_seccion,
                        })

                    else:
                        for candidato in [cell0, cell1]:
                            if (candidato
                                    and candidato == candidato.upper()
                                    and len(candidato) > 4
                                    and not re.match(r"^\d", candidato)
                                    and not any(k in candidato.upper() for k in SKIP_KEYWORDS)):
                                current_seccion = candidato.strip()
                                break

    return items



def _extraer_items_texto(texto: str) -> List[dict]:
    """Fallback: extrae ítems del texto plano con regex."""
    items: List[dict] = []
    current_seccion   = "General"

    KNOWN_SECTIONS = re.compile(
        r"^(TÍTULO|PLANTEAMIENTO DEL PROBLEMA|MARCO TEÓRICO|"
        r"HIPÓTESIS Y VARIABLES|MARCO METODOLÓGICO|ASPECTOS ADMINISTRATIVOS|"
        r"REFERENCIAS BIBLIOGRÁFICAS)$",
        re.IGNORECASE,
    )
    CAPS_PATTERN = re.compile(r"^[A-ZÁÉÍÓÚÜÑ\s/\(\)\-–]{6,}$")
    ITEM_PATTERN = re.compile(r"^(\d{1,2})\s+(.{10,})")
    SKIP_LINES   = {"ITEM", "ÍTEMS", "N°", "TOTAL", "SUB TOTAL",
                    "TABLA DE VALORES", "OBSERVACIONES"}

    buffer_num:  Optional[int]       = None
    buffer_desc: List[str]           = []

    def flush():
        nonlocal buffer_num, buffer_desc
        if buffer_num and buffer_desc:
            desc = " ".join(buffer_desc).strip()
            desc = re.sub(r"\s+[xX]\s*$", "", desc).strip()
            if len(desc) > 10:
                items.append({
                    "numero":      buffer_num,
                    "descripcion": desc,
                    "seccion":     current_seccion,
                })
        buffer_num  = None
        buffer_desc = []

    for line in [l.strip() for l in texto.split("\n") if l.strip()]:
        if line.upper() in SKIP_LINES:
            continue

        if KNOWN_SECTIONS.match(line) or (CAPS_PATTERN.match(line) and len(line) > 6):
            flush()
            if not re.match(r"^[0-9xX\s]+$", line):
                current_seccion = line
            continue

        m = ITEM_PATTERN.match(line)
        if m:
            flush()
            buffer_num  = int(m.group(1))
            buffer_desc = [m.group(2).strip()]
        elif buffer_num and not re.match(r"^[0-9xX\s]+$", line):
            buffer_desc.append(line)

    flush()
    return items



def _agrupar_por_seccion(items: List[dict]) -> dict:
    """Devuelve {nombre_seccion: [numero_item, ...]}."""
    secciones: dict = {}
    for item in items:
        secciones.setdefault(item["seccion"], []).append(item["numero"])
    return secciones


def _extraer_escala(texto: str) -> dict:
    """Extrae la escala de valoración. Default: UPAO (3=Excelente … 0=Insuficiente)."""
    escala = {3: "Excelente", 2: "Bueno", 1: "Regular", 0: "Insuficiente"}

    for desc, default_val in [("excelente", 3), ("bueno", 2), ("regular", 1), ("insuficiente", 0)]:
        m = re.search(rf"(?i){desc}\s+(\d)", texto)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 5:
                escala[val] = desc.capitalize()

    return escala


def _extraer_vigesimal(texto: str) -> list:
    """Extrae la tabla puntaje → nota vigesimal. Default: tabla UPAO."""
    default = [
        (96, 100, 20), (91, 95, 19), (86, 90, 18), (81, 85, 17),
        (76, 80, 16),  (71, 75, 15), (66, 70, 14), (61, 65, 13),
        (56, 60, 12),  (51, 55, 11), (46, 50, 10), (41, 45,  9),
        (36, 40,  8),  (31, 35,  7), (26, 30,  6), (21, 25,  5),
        (0,  20,  0),
    ]

    pares = re.findall(r"(\d{1,3})[-–](\d{1,3})\s+(\d{1,2})\b", texto)
    if len(pares) >= 5:
        try:
            tabla = [(int(a), int(b), int(n)) for a, b, n in pares if int(n) <= 20]
            if tabla:
                return sorted(tabla, key=lambda x: x[0], reverse=True)
        except Exception:
            pass

    return default


def puntaje_a_nota_dinamico(puntaje: int, tabla_vigesimal: list) -> int:
    """Convierte puntaje a nota vigesimal usando la tabla de la rúbrica dinámica."""
    for pmin, pmax, nota in tabla_vigesimal:
        if pmin <= puntaje <= pmax:
            return nota
    return 0


def rubrica_a_texto_prompt(rubrica: dict) -> str:
    """
    Convierte la rúbrica parseada a texto Markdown para inyectar en el prompt del Auditor.
    """
    lineas = ["| N° | Ítem de la Rúbrica | Puntaje (0-3) |",
              "|----|---------------------|--------------|"]
    ultima_seccion = None

    for item in rubrica.get("items", []):
        sec = item["seccion"]
        if sec != ultima_seccion:
            lineas.append(f"\n**{sec}**\n")
            ultima_seccion = sec
        lineas.append(f"| {item['numero']:02d} | {item['descripcion']} | ___ |")

    return "\n".join(lineas)
