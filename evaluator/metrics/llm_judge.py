import os
import logging
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

class ItemRubricaEvaluado(BaseModel):
    item_id: str = Field(description="ID del ítem en la rúbrica (ej. '4.1', '2.3')")
    descripcion: str = Field(description="Descripción del criterio de la rúbrica")
    pts_max: float = Field(description="Puntaje máximo asignable a este ítem")
    pts_obtenido: float = Field(description="Puntaje asignado (0, 50% de pts_max, o pts_max)")
    razon: str = Field(description="Explicación detallada de por qué se asignó esta calificación")

class EvaluacionSeccion(BaseModel):
    secciones_seleccionadas: List[str] = Field(description="Secciones de la rúbrica especializada seleccionadas")
    items: List[ItemRubricaEvaluado] = Field(description="Lista de ítems evaluados")
    puntaje_total: float = Field(description="Suma total de los puntajes obtenidos")
    puntaje_maximo: float = Field(description="Suma total de los puntajes máximos de los ítems seleccionados")

def cargar_rubrica_metodologica() -> str:
    """Lee el archivo rubrica.md de la carpeta del proyecto."""
    for pos in ["rubrica.md", "../rubrica.md", "poc_langgraph_mentoria/rubrica.md"]:
        if os.path.isfile(pos):
            with open(pos, "r", encoding="utf-8") as f:
                return f.read()
    
    abs_path = r"c:\Users\Administrador\Downloads\langgraph-red\poc_langgraph_mentoria\rubrica.md"
    if os.path.isfile(abs_path):
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()
            
    return "Rúbrica metodológica no encontrada en el sistema."

_PROMPT_JUEZ_LLM = """
Eres un Juez Metodológico de tesis de Ingeniería (estilo G-Eval). Evaluador de alta precisión.
Tu tarea es evaluar la calidad metodológica de la sección de tesis del estudiante utilizando los criterios de la RÚBRICA DE EVALUACIÓN DE CALIDAD METODOLÓGICA especializada adjunta.

RÚBRICA DE EVALUACIÓN (SECCIONES APLICABLES):
{rubrica}

---

ENTRADAS A EVALUAR:
- Sección Objetivo de la Tesis: **{seccion_objetivo}**
- Texto a Evaluar:
{texto}

---

REGLAS DE CALIFICACIÓN POR ÍTEM:
- Debes evaluar CADA ítem que aparezca en las secciones de la rúbrica proporcionadas arriba.
- Para cada ítem, asigna:
  * Puntaje máximo (pts_max) si se cumple COMPLETAMENTE.
  * 50% de pts_max si se cumple PARCIALMENTE.
  * 0 si NO SE CUMPLE.
- Escribe una justificación académica clara para cada ítem en "razon".
- Calcula de forma precisa e interna:
  * puntaje_maximo: suma de todos los pts_max.
  * puntaje_total: suma de todos los pts_obtenido.

Responde en formato estructurado de JSON.
"""

def _ejecutar_un_juez(
    model_name: str,
    temperature: float,
    seccion_objetivo: str,
    texto: str,
    rubrica_content: str,
    api_key: str
) -> Optional[EvaluacionSeccion]:
    """Ejecuta una llamada de evaluación a un modelo/configuración específica."""
    try:
        llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            temperature=temperature,
            max_retries=2,
            timeout=180.0
        ).with_structured_output(EvaluacionSeccion)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", _PROMPT_JUEZ_LLM)
        ])
        
        chain = prompt | llm
        resultado = chain.invoke({
            "rubrica": rubrica_content,
            "seccion_objetivo": seccion_objetivo,
            "texto": texto
        })
        if resultado and resultado.items:
            resultado.puntaje_total = sum(item.pts_obtenido for item in resultado.items)
            resultado.puntaje_maximo = sum(item.pts_max for item in resultado.items)
        return resultado
    except Exception as exc:
        logger.warning(f"Juez LLM con modelo {model_name} y temp {temperature} falló: {exc}")
        return None

def filtrar_rubrica_por_seccion(seccion_objetivo: str) -> str:
    """Filtra rubrica.md para quedarse solo con las secciones aplicables a seccion_objetivo."""
    rubrica_content = cargar_rubrica_metodologica()
    if not rubrica_content or "Rúbrica metodológica no encontrada" in rubrica_content:
        return rubrica_content

    import re
    from backend.config import _kw_seccion

    MAP_SECCION_OBJETIVO_A_NUMEROS = {
        "1. Título del proyecto":                    [1],
        "1.1 Descripción y delimitación":            [2],
        "1.1.2 Problema central (formulación)":      [2, 3],
        "1.2 Objetivos (General y Específicos)":     [4],
        "1.3 Importancia del estudio":               [5],
        "1.4 Justificación del estudio":             [5],
        "2.2 Investigaciones antecedentes":          [7],
        "2.3 Base teórica (Variables)":              [7],
        "2.4 Definición de términos básicos":        [7],
        "3.1–3.2 Hipótesis":                         [8],
        "3.3 Variables (Operacionalización)":        [9],
        "3.4 Matriz de consistencia":                [10],
        "4.1–4.3 Tipo, Método y Diseño":             [11, 12],
        "4.4 Población y muestra":                   [13],
        "4.5 Instrumentos de recolección de datos":  [14],
        "4.6 Procedimiento de ejecución":            [14],
        "4.7 Análisis de datos":                     [15],
        "5. Aspectos administrativos":               [6],
        "III. Referencias bibliográficas":           [7],
    }

    numeros = None
    direct = MAP_SECCION_OBJETIVO_A_NUMEROS.get(seccion_objetivo)
    if direct:
        numeros = direct
    else:
        m = re.match(r'^(\d[\d\.]*)', seccion_objetivo.strip())
        prefijo_num = m.group(1).rstrip('.') if m else None
        if prefijo_num:
            for k, val in MAP_SECCION_OBJETIVO_A_NUMEROS.items():
                m2 = re.match(r'^(\d[\d\.]*)', k.strip())
                if m2 and m2.group(1).rstrip('.') == prefijo_num:
                    numeros = val
                    break
        if not numeros:
            kw = _kw_seccion(seccion_objetivo)
            if kw:
                mejor_jaccard = 0.0
                for k, val in MAP_SECCION_OBJETIVO_A_NUMEROS.items():
                    kw_k = _kw_seccion(k)
                    inter = len(kw & kw_k)
                    if inter == 0:
                        continue
                    union = len(kw | kw_k)
                    jaccard = inter / union if union else 0.0
                    if jaccard > mejor_jaccard:
                        mejor_jaccard = jaccard
                        numeros = val

    if not numeros:
        if "vista general" in seccion_objetivo.lower():
            numeros = [1, 2, 3, 4, 8, 11, 12]
        else:
            return rubrica_content

    pattern = r'\*\*(\d+)\\\.\s+([^*]+)\*\*'
    matches = list(re.finditer(pattern, rubrica_content))
    
    secciones_texto = {}
    for i, match in enumerate(matches):
        num = int(match.group(1))
        start_idx = match.start()
        if i + 1 < len(matches):
            end_idx = matches[i + 1].start()
        else:
            escala_match = re.search(r'\*\*ESCALA DE', rubrica_content)
            end_idx = escala_match.start() if escala_match else len(rubrica_content)
        secciones_texto[num] = rubrica_content[start_idx:end_idx].strip()

    partes = []
    for n in sorted(numeros):
        if n in secciones_texto:
            partes.append(secciones_texto[n])

    if partes:
        cabecera = rubrica_content.split("**RÚBRICA DETALLADA POR SECCIÓN**")[0]
        return cabecera + "\n\n**RÚBRICA DETALLADA (SECCIONES APLICABLES)**\n\n" + "\n\n".join(partes)
    
    return rubrica_content

def evaluar_con_juez_llm(seccion_objetivo: str, texto: str, es_panel: bool = True) -> EvaluacionSeccion:
    """
    Evalúa un texto con el Juez LLM (G-Eval).
    Si es_panel es True, usa un panel de hasta 3 configuraciones/modelos de LLM y calcula el consenso.
    """
    if not texto.strip():
        return EvaluacionSeccion(
            secciones_seleccionadas=[],
            items=[],
            puntaje_total=0.0,
            puntaje_maximo=1.0
        )
        
    rubrica_content = filtrar_rubrica_por_seccion(seccion_objetivo)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    
    if not es_panel:
        res = _ejecutar_un_juez("gpt-4o-mini", 0.0, seccion_objetivo, texto, rubrica_content, api_key)
        if res:
            return res
        raise ValueError("El Juez LLM único falló al evaluar el texto.")

    configuraciones = [
        {"model": "gpt-4o-mini", "temp": 0.0},
        {"model": "gpt-4o", "temp": 0.2},
        {"model": "gpt-3.5-turbo", "temp": 0.1}
    ]
    
    resultados: List[EvaluacionSeccion] = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futuros = []
        for config in configuraciones:
            futuros.append(
                executor.submit(
                    _ejecutar_un_juez,
                    config["model"],
                    config["temp"],
                    seccion_objetivo,
                    texto,
                    rubrica_content,
                    api_key
                )
            )
            
        for i, f in enumerate(futuros):
            res = f.result()
            if res:
                resultados.append(res)
            else:
                temp_fallback = configuraciones[i]["temp"] + 0.3
                fallback_res = _ejecutar_un_juez("gpt-4o-mini", temp_fallback, seccion_objetivo, texto, rubrica_content, api_key)
                if fallback_res:
                    resultados.append(fallback_res)

    if not resultados:
        res = _ejecutar_un_juez("gpt-4o-mini", 0.0, seccion_objetivo, texto, rubrica_content, api_key)
        if res:
            return res
        raise ValueError("Todos los jueces del panel y los fallbacks fallaron al evaluar el texto.")
        
    total_scores = [r.puntaje_total for r in resultados]
    avg_score = sum(total_scores) / len(total_scores)
    
    mejor_juez = min(resultados, key=lambda r: abs(r.puntaje_total - avg_score))
    
    pts_total = sum(item.pts_obtenido for item in mejor_juez.items)
    pts_max = sum(item.pts_max for item in mejor_juez.items)
    
    return EvaluacionSeccion(
        secciones_seleccionadas=mejor_juez.secciones_seleccionadas,
        items=mejor_juez.items,
        puntaje_total=pts_total,
        puntaje_maximo=pts_max
    )
