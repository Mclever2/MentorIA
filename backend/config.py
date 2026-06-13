"""
Configuración central del sistema de mentoría académica UPAO.

Contiene:
  - RUBRICA_ITEMS_UPAO: Los 33 ítems exactos de la ficha oficial de evaluación
  - SECCION_ITEMS_MAP:  Qué ítems evaluar según la sección elegida
  - SECCIONES_TESIS:    Opciones del menú + query de búsqueda para ChromaDB
  - LIBRARY_CHROMA_PATH / BOOKS_PRELOAD_DIR: Paths para la biblioteca de libros
"""

import os
import re
import unicodedata

_ROOT = os.path.dirname(os.path.dirname(__file__))
LIBRARY_CHROMA_PATH = os.path.join(_ROOT, "chroma_db", "biblioteca")
BOOKS_PRELOAD_DIR   = os.path.join(_ROOT, "books")


RUBRICA_ITEMS_UPAO: dict[int, str] = {
    1:  "El título es claro, conciso y refleja fielmente el contenido y el propósito de la investigación.",
    2:  "El título articula las variables, espacio y tiempo de la investigación.",
    3:  "El estudio se enmarca en la línea de investigación que promueve el programa de estudios.",

    4:  "El problema central del estudio describe con claridad la realidad social, económica, cultural, científica o tecnológica que motiva la investigación.",
    5:  "El problema central del estudio recoge el estado de la investigación (antecedentes) de las variables de estudio.",
    6:  "El objetivo general guarda relación con el problema.",
    7:  "Los objetivos específicos derivan del objetivo general.",
    8:  "Se explica por qué el estudio es relevante y qué aportaciones hará al campo de investigación.",
    9:  "El problema está claramente formulado.",
    10: "Se detalla la justificación de la investigación, precisando cómo contribuirá al conocimiento existente y su impacto potencial.",

    11: "Los antecedentes guardan relación con el problema de investigación.",
    12: "Las bases teóricas / científicas proporcionan una base sólida con teorías, modelos y conceptos relevantes.",
    13: "La definición de términos básicos define claramente términos técnicos y específicos para evitar confusiones.",
    14: "Las citas textuales o de paráfrasis son concordantes con la naturaleza de las variables.",
    15: "Los textos y autores citados se encuentran en las referencias bibliográficas.",
    16: "Los autores asumen una postura crítica y no solo copian las ideas de los autores citados.",
    17: "Se citan a los autores conforme a las normas internacionales (HARVARD, VANCOUVER, APA, ISO).",

    18: "Las hipótesis guardan relación con el problema de investigación.",
    19: "Si hay hipótesis específicas, éstas derivan de problemas derivados.",
    20: "Es clara la definición operacional de las variables: dimensiones o indicadores.",
    21: "La matriz de consistencia asegura que todos los elementos del estudio están alineados.",

    22: "El tipo de investigación y el método de investigación guardan relación con el problema de investigación.",
    23: "Se presenta el esquema (gráfico) del diseño de investigación.",
    24: "Define claramente la población y muestra de estudio. Si fuera el caso, se hace uso del cálculo estadístico para el tamaño y selección de la muestra.",
    25: "Describe los instrumentos de recolección de datos de manera detallada en correspondencia con el problema y diseño metodológico.",
    26: "Especifica el procedimiento de ejecución del estudio.",
    27: "Especifica las técnicas de procesamiento y análisis de datos apropiadas conforme al problema y naturaleza de las variables.",

    28: "El cronograma detalla todas las actividades y plazos para el desarrollo del proyecto.",
    29: "Se detallan claramente los recursos humanos y materiales para ejecutar el proyecto.",
    30: "El presupuesto estima los costos de los bienes y servicios requeridos para ejecutar el proyecto.",
    31: "Se precisa las fuentes de financiamiento para ejecutar el proyecto: propia y/o externas.",

    32: "Se encuentran incorporados todos los autores citados.",
    33: "La redacción de las referencias bibliográficas es conforme a las normas internacionales (HARVARD, VANCOUVER, APA, ISO).",
}

TABLA_VIGESIMAL: list[tuple[int, int, int]] = [
    (96, 99, 20), (91, 95, 19), (86, 90, 18), (81, 85, 17),
    (76, 80, 16), (71, 75, 15), (66, 70, 14), (61, 65, 13),
    (56, 60, 12), (51, 55, 11), (46, 50, 10), (41, 45,  9),
    (36, 40,  8), (31, 35,  7), (26, 30,  6), (21, 25,  5),
    (0,  20,  0),
]


def puntaje_a_nota(puntaje: int) -> int:
    """Convierte puntaje 0-99 a nota vigesimal 0-20 según tabla UPAO."""
    for pmin, pmax, nota in TABLA_VIGESIMAL:
        if pmin <= puntaje <= pmax:
            return nota
    return 0


SECCION_ITEMS_MAP: dict[str, list[int]] = {
    "1. Título del proyecto":                    [1, 2, 3],
    "1.1 Descripción y delimitación":            [4, 5],
    "1.1.2 Problema central (formulación)":      [4, 5, 9],
    "1.2 Objetivos (General y Específicos)":     [6, 7],
    "1.3 Importancia del estudio":               [8],
    "1.4 Justificación del estudio":             [10],
    "2.2 Investigaciones antecedentes":          [11, 15],
    "2.3 Base teórica (Variables)":              [12, 14, 16, 17],
    "2.4 Definición de términos básicos":        [13],
    "3.1–3.2 Hipótesis":                         [18, 19],
    "3.3 Variables (Operacionalización)":        [20],
    "3.4 Matriz de consistencia":                [21],
    "4.1–4.3 Tipo, Método y Diseño":             [22, 23],
    "4.4 Población y muestra":                   [24],
    "4.5 Instrumentos de recolección de datos":  [25],
    "4.6 Procedimiento de ejecución":            [26],
    "4.7 Análisis de datos":                     [27],
    "5. Aspectos administrativos":               [28, 29, 30, 31],
    "III. Referencias bibliográficas":           [32, 33],
}

SECCIONES_TESIS: list[dict] = [
    {
        "nombre": "1. Título del proyecto",
        "query":  "título proyecto investigación variables espacio tiempo línea investigación",
    },
    {
        "nombre": "1.1 Descripción y delimitación",
        "query":  "descripción problema central delimitación realidad antecedentes variables",
    },
    {
        "nombre": "1.1.2 Problema central (formulación)",
        "query":  "formulación problema central estudio planteamiento pregunta investigación",
    },
    {
        "nombre": "1.2 Objetivos (General y Específicos)",
        "query":  "objetivo general específicos investigación derivan problema",
    },
    {
        "nombre": "1.3 Importancia del estudio",
        "query":  "importancia relevancia aportaciones campo investigación estudio",
    },
    {
        "nombre": "1.4 Justificación del estudio",
        "query":  "justificación teórica práctica metodológica social investigación",
    },
    {
        "nombre": "2.2 Investigaciones antecedentes",
        "query":  "antecedentes investigaciones previas estudios relacionados citados",
    },
    {
        "nombre": "2.3 Base teórica (Variables)",
        "query":  "base teórica científica modelos teorías conceptos citas paráfrasis",
    },
    {
        "nombre": "2.4 Definición de términos básicos",
        "query":  "definición términos básicos técnicos específicos glosario",
    },
    {
        "nombre": "3.1–3.2 Hipótesis",
        "query":  "hipótesis general específicas supuestos básicos problema relación",
    },
    {
        "nombre": "3.3 Variables (Operacionalización)",
        "query":  "variables definición operacional dimensiones indicadores ítems escala",
    },
    {
        "nombre": "3.4 Matriz de consistencia",
        "query":  "matriz de consistencia alineación elementos problema objetivo hipótesis variable",
    },
    {
        "nombre": "4.1–4.3 Tipo, Método y Diseño",
        "query":  "tipo investigación método diseño esquema gráfico investigación",
    },
    {
        "nombre": "4.4 Población y muestra",
        "query":  "población muestra estudio cálculo estadístico selección criterios",
    },
    {
        "nombre": "4.5 Instrumentos de recolección de datos",
        "query":  "instrumentos técnicas recolección datos correspondencia diseño",
    },
    {
        "nombre": "4.6 Procedimiento de ejecución",
        "query":  "procedimiento ejecución estudio pasos etapas actividades",
    },
    {
        "nombre": "4.7 Análisis de datos",
        "query":  "técnicas procesamiento análisis datos estadísticas naturaleza variables",
    },
    {
        "nombre": "5. Aspectos administrativos",
        "query":  "cronograma actividades recursos humanos materiales presupuesto financiamiento",
    },
    {
        "nombre": "III. Referencias bibliográficas",
        "query":  "referencias bibliográficas autores citados normas APA VANCOUVER HARVARD",
    },
]


_STOP_CFG = {
    "de", "del", "la", "el", "los", "las", "un", "una", "y", "e", "o", "u",
    "con", "en", "al", "para", "por", "que", "se", "su", "sus", "es", "son",
    "a", "ante", "bajo", "desde", "sin", "sobre", "tras", "como",
    "estudio", "investigacion", "proyecto",
}


def _kw_seccion(texto: str) -> set[str]:
    """Palabras significativas de un nombre de sección (sin números, acentos, ni stop words)."""
    sin_acentos = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    tokens = re.sub(r'[\d\.\,\-–\(\)\[\]/]', ' ', sin_acentos.lower()).split()
    return {t for t in tokens if len(t) > 2 and t not in _STOP_CFG}


def _prefijo_num(nombre: str) -> str:
    """Prefijo numérico de una sección: '2.1. Título' → '2.1'."""
    m = re.match(r'^(\d[\d\.]*)', nombre.strip())
    return m.group(1).rstrip('.') if m else ""


def _prefijos_rango(seccion: str) -> list[str]:
    """
    Prefijos de una sección, expandiendo rangos explícitos.
    '4.1–4.3 Tipo, Método y Diseño' → ['4.1', '4.2', '4.3']
    '1.2 Objetivos (General y Específicos)' → ['1.2']
    """
    m = re.match(r'^(\d[\d\.]*)\s*[–\-]\s*(\d[\d\.]*)', seccion.strip())
    if not m:
        p = _prefijo_num(seccion)
        return [p] if p else []
    ini = m.group(1).rstrip('.')
    fin = m.group(2).rstrip('.')
    pi = [int(x) for x in ini.split('.')]
    pf = [int(x) for x in fin.split('.')]
    if len(pi) != len(pf) or not pi or pi[:-1] != pf[:-1]:
        return [ini]
    padre = '.'.join(str(x) for x in pi[:-1])
    return [f"{padre}.{i}" if padre else str(i) for i in range(pi[-1], pf[-1] + 1)]


def _seccion_rubrica_para(seccion: str) -> str | None:
    """
    Clave de SECCION_ITEMS_MAP que gobierna la rúbrica de `seccion` (o None).

    Estrategia en cascada:
      1. Coincidencia exacta de nombre.
      2. Prefijo numérico exacto (ej. '1.1.1' → clave con prefijo '1.1.1').
      3. Mayor overlap de palabras clave (PDFs con distinta numeración).
      4. Prefijo del padre inmediato (ej. '1.2.1' → clave con prefijo '1.2').
    """
    if seccion in SECCION_ITEMS_MAP:
        return seccion

    prefijo_num = _prefijo_num(seccion) or None
    if prefijo_num:
        for k in SECCION_ITEMS_MAP:
            if _prefijo_num(k) == prefijo_num:
                return k

    kw = _kw_seccion(seccion)
    if kw:
        mejor_jaccard = 0.0
        mejor_key: str | None = None
        for k in SECCION_ITEMS_MAP:
            kw_k  = _kw_seccion(k)
            inter = len(kw & kw_k)
            if inter == 0:
                continue
            union   = len(kw | kw_k)
            jaccard = inter / union if union else 0.0
            if jaccard > mejor_jaccard:
                mejor_jaccard = jaccard
                mejor_key     = k
        if mejor_jaccard > 0:
            return mejor_key

    if prefijo_num and '.' in prefijo_num:
        padre = prefijo_num.rsplit('.', 1)[0]
        for k in SECCION_ITEMS_MAP:
            if _prefijo_num(k) == padre:
                return k

    return None


def _buscar_items_seccion(seccion: str) -> list[int]:
    """Ítems de SECCION_ITEMS_MAP que aplican a `seccion` (vía la clave de rúbrica)."""
    key = _seccion_rubrica_para(seccion)
    return list(SECCION_ITEMS_MAP.get(key, [])) if key else []


def prefijos_evaluacion_para_seccion(seccion: str) -> list[str]:
    """
    Prefijos numéricos que delimitan la UNIDAD de evaluación de `seccion`,
    anclada a la sección de rúbrica que la gobierna.

    Por qué: el menú ofrece encabezados crudos del TOC (p.ej. '1.2.1 Objetivo
    general'), pero la rúbrica define la unidad un nivel arriba ('1.2 Objetivos
    (General y Específicos)', ítems 6 y 7). Evaluar solo la hoja deja fuera a la
    sub-sección hermana ('1.2.2 Objetivos específicos') y produce falsos errores
    (ej. "faltan objetivos específicos" cuando sí existen). Anclando al prefijo
    de la rúbrica, el RAG recupera TODA la unidad.

    Devuelve:
      - los prefijos del grupo de rúbrica cuando éste es ancestro (o igual) de la
        hoja elegida (ej. '1.2.1' → ['1.2']; '4.2' → ['4.1','4.2','4.3']);
      - los prefijos propios de la sección en caso contrario (sección ya amplia,
        o sin rúbrica resoluble).
    """
    propios = _prefijos_rango(seccion)
    key = _seccion_rubrica_para(seccion)
    if not key:
        return propios

    rubrica_prefijos = _prefijos_rango(key)
    hoja = _prefijo_num(seccion)
    if not hoja or not rubrica_prefijos:
        return propios or rubrica_prefijos

    for rp in rubrica_prefijos:
        if hoja == rp or hoja.startswith(rp + "."):
            return rubrica_prefijos

    return propios


def get_items_texto_para_seccion(seccion: str) -> str:
    """Genera la tabla de ítems relevantes para una sección, lista para inyectar en el prompt."""
    items_nums = _buscar_items_seccion(seccion) or list(RUBRICA_ITEMS_UPAO.keys())
    lineas = ["| N° | Ítem de la Rúbrica UPAO | Puntaje (0-3) |",
              "|----|-----------------------------|--------------|"]
    for num in items_nums:
        desc = RUBRICA_ITEMS_UPAO.get(num, "Ítem sin descripción")
        lineas.append(f"| {num:02d} | {desc} | ___ |")
    return "\n".join(lineas)


def get_puntaje_maximo_seccion(seccion: str) -> int:
    """Puntaje máximo posible para la sección (nro. de ítems × 3)."""
    return len(_buscar_items_seccion(seccion)) * 3


DEPENDENCIAS_SECCIONES: dict[str, list[str]] = {
    "1. Título del proyecto": [
        "1.1.2 Problema central (formulación)",
        "1.2 Objetivos (General y Específicos)",
        "3.3 Variables (Operacionalización)",
        "3.1–3.2 Hipótesis",
        "2.3 Base teórica (Variables)",
        "4.1–4.3 Tipo, Método y Diseño",
    ],
    "1.1 Descripción y delimitación": [
        "1. Título del proyecto",
        "1.2 Objetivos (General y Específicos)",
    ],
    "1.1.2 Problema central (formulación)": [
        "1. Título del proyecto",
        "1.2 Objetivos (General y Específicos)",
        "3.1–3.2 Hipótesis",
    ],
    "1.2 Objetivos (General y Específicos)": [
        "1.1.2 Problema central (formulación)",
        "3.1–3.2 Hipótesis",
        "3.3 Variables (Operacionalización)",
    ],
    "1.3 Importancia del estudio": [
        "1.1.2 Problema central (formulación)",
    ],
    "1.4 Justificación del estudio": [
        "1.1.2 Problema central (formulación)",
        "1.2 Objetivos (General y Específicos)",
    ],
    "2.2 Investigaciones antecedentes": [
        "1.1.2 Problema central (formulación)",
        "3.3 Variables (Operacionalización)",
    ],
    "2.3 Base teórica (Variables)": [
        "3.3 Variables (Operacionalización)",
        "1. Título del proyecto",
    ],
    "2.4 Definición de términos básicos": [
        "3.3 Variables (Operacionalización)",
        "2.3 Base teórica (Variables)",
    ],
    "3.1–3.2 Hipótesis": [
        "1.1.2 Problema central (formulación)",
        "1.2 Objetivos (General y Específicos)",
        "3.3 Variables (Operacionalización)",
    ],
    "3.3 Variables (Operacionalización)": [
        "3.4 Matriz de consistencia",
        "4.1–4.3 Tipo, Método y Diseño",
        "4.5 Instrumentos de recolección de datos",
    ],
    "3.4 Matriz de consistencia": [
        "3.3 Variables (Operacionalización)",
        "4.1–4.3 Tipo, Método y Diseño",
        "4.7 Análisis de datos",
    ],
    "4.1–4.3 Tipo, Método y Diseño": [
        "3.3 Variables (Operacionalización)",
        "3.4 Matriz de consistencia",
        "4.4 Población y muestra",
    ],
    "4.4 Población y muestra": [
        "4.1–4.3 Tipo, Método y Diseño",
        "4.5 Instrumentos de recolección de datos",
        "3.3 Variables (Operacionalización)",
    ],
    "4.5 Instrumentos de recolección de datos": [
        "3.3 Variables (Operacionalización)",
        "4.1–4.3 Tipo, Método y Diseño",
        "4.4 Población y muestra",
    ],
    "4.6 Procedimiento de ejecución": [
        "4.1–4.3 Tipo, Método y Diseño",
        "4.4 Población y muestra",
        "4.5 Instrumentos de recolección de datos",
    ],
    "4.7 Análisis de datos": [
        "3.3 Variables (Operacionalización)",
        "4.1–4.3 Tipo, Método y Diseño",
        "4.5 Instrumentos de recolección de datos",
    ],
    "5. Aspectos administrativos": [
        "4.1–4.3 Tipo, Método y Diseño",
        "4.4 Población y muestra",
        "4.6 Procedimiento de ejecución",
    ],
    "III. Referencias bibliográficas": [
        "3.3 Variables (Operacionalización)",
        "4.1–4.3 Tipo, Método y Diseño",
        "4.5 Instrumentos de recolección de datos",
    ],
}

MAX_ITERACIONES_DEFAULT  = 3
MAX_RONDAS_DEBATE_DEFAULT = 2
