import os
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# Rúbrica del juez según el tipo de investigación detectado.
_RUBRICA_POR_TIPO = {
    "cuantitativa": "rubrica.md",
    "cualitativa":  "rubrica_cualitativa.md",
    "mixta":        "rubrica_mixto.md",
    "tecnologica":  "rubrica_tecnologico.md",
    "innovacion":   "rubrica_innovacion.md",
}
_RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

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

def cargar_rubrica_metodologica(tipo: Optional[str] = None) -> str:
    """Lee la rúbrica del juez según el tipo de investigación.

    cuantitativa→rubrica.md, cualitativa→rubrica_cualitativa.md, mixta→rubrica_mixto.md,
    tecnologica→rubrica_tecnologico.md, innovacion→rubrica_innovacion.md.
    Si no se encuentra la específica, cae a la cuantitativa.
    """
    try:
        from backend.enfoque import normalizar_tipo
        fname = _RUBRICA_POR_TIPO.get(normalizar_tipo(tipo), "rubrica.md")
    except Exception:
        fname = "rubrica.md"

    candidatos = [str(_RAIZ_PROYECTO / fname), fname, os.path.join("..", fname),
                  os.path.join("poc_langgraph_mentoria", fname)]
    for pos in candidatos:
        if os.path.isfile(pos):
            with open(pos, "r", encoding="utf-8") as f:
                return f.read()

    if fname != "rubrica.md":
        logger.warning(f"[juez] No se encontró {fname}; uso rubrica.md (cuantitativa).")
        return cargar_rubrica_metodologica(None)
    return "Rúbrica metodológica no encontrada en el sistema."

_PROMPT_JUEZ_LLM = """
Eres un Juez Metodológico de tesis de Ingeniería (estilo G-Eval). Evaluador de alta precisión.
Tu tarea es evaluar la calidad metodológica de la sección de tesis del estudiante utilizando los criterios de la RÚBRICA DE EVALUACIÓN DE CALIDAD METODOLÓGICA especializada adjunta.

IMPORTANTE: esto es un PROYECTO/propuesta de tesis (estructura de plan), que AÚN NO tiene
Resultados, Discusión ni Conclusiones. Evalúa el PLAN y la coherencia metodológica; NO exijas
resultados, hallazgos ni conclusiones reales. Si un ítem habla de "resultados/contribución", evalúa
que esté bien PLANIFICADO/previsto, no que ya exista.

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

def _parsear_secciones_rubrica(rubrica_content: str) -> list[tuple[int, str, str]]:
    """Devuelve [(num, titulo, cuerpo)] de la rúbrica, parseando sus encabezados."""
    import re
    detallada = rubrica_content
    if "RÚBRICA DETALLADA POR SECCIÓN" in rubrica_content:
        detallada = rubrica_content.split("**RÚBRICA DETALLADA POR SECCIÓN**", 1)[-1]
    pattern = r'\*\*(\d+)\\?\.\s+([^*]+?)\*\*'
    matches = list(re.finditer(pattern, detallada))
    fin = re.search(r'\*\*ESCALA DE', detallada)
    fin_idx = fin.start() if fin else len(detallada)
    secciones = []
    for i, m in enumerate(matches):
        num = int(m.group(1))
        titulo = m.group(2).strip()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else fin_idx
        secciones.append((num, titulo, detallada[start:end].strip()))
    return secciones


def filtrar_rubrica_por_seccion(seccion_objetivo: str, tipo: Optional[str] = None) -> str:
    """Filtra la rúbrica (del tipo dado) a la(s) sección(es) aplicable(s) a seccion_objetivo.

    Genérico: parsea los encabezados de la rúbrica cargada y empareja seccion_objetivo
    con el mejor título por palabras clave (sirve para las 5 rúbricas, no solo la cuanti).
    """
    rubrica_content = cargar_rubrica_metodologica(tipo)
    if not rubrica_content or "Rúbrica metodológica no encontrada" in rubrica_content:
        return rubrica_content

    from backend.config import _kw_seccion

    secciones = _parsear_secciones_rubrica(rubrica_content)
    if not secciones:
        return rubrica_content

    cuerpos: list[str] = []
    if "vista general" in seccion_objetivo.lower():
        cuerpos = [c for _, _, c in secciones]
    else:
        kw = _kw_seccion(seccion_objetivo)
        if kw:
            mejor_j, mejor_cuerpo = 0.0, None
            for _, titulo, cuerpo in secciones:
                kw_t = _kw_seccion(titulo)
                inter = len(kw & kw_t)
                if not inter:
                    continue
                j = inter / len(kw | kw_t)
                if j > mejor_j:
                    mejor_j, mejor_cuerpo = j, cuerpo
            if mejor_cuerpo:
                cuerpos = [mejor_cuerpo]

    if not cuerpos:
        return rubrica_content  # sin match claro: usar la rúbrica completa

    cabecera = rubrica_content.split("**RÚBRICA DETALLADA POR SECCIÓN**")[0]
    return cabecera + "\n\n**RÚBRICA DETALLADA (SECCIONES APLICABLES)**\n\n" + "\n\n".join(cuerpos)

def evaluar_con_juez_llm(seccion_objetivo: str, texto: str, es_panel: bool = True,
                         tipo: Optional[str] = None) -> EvaluacionSeccion:
    """
    Evalúa un texto con el Juez LLM (G-Eval) usando la rúbrica del TIPO de investigación.
    Si es_panel es True, usa un panel de hasta 3 configuraciones/modelos de LLM y calcula el consenso.
    """
    if not texto.strip():
        return EvaluacionSeccion(
            secciones_seleccionadas=[],
            items=[],
            puntaje_total=0.0,
            puntaje_maximo=1.0
        )

    rubrica_content = filtrar_rubrica_por_seccion(seccion_objetivo, tipo)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    
    if not es_panel:
        res = _ejecutar_un_juez("gpt-4o-mini", 0.0, seccion_objetivo, texto, rubrica_content, api_key)
        if res:
            return res
        raise ValueError("El Juez LLM único falló al evaluar el texto.")

    # Jurado de 3 modelos distintos (≥3 para poder descartar al atípico vía
    # consenso por medoide). Todos soportan salida estructurada nativa, así que
    # no hay warning de json_schema. Temperaturas bajas → más reproducible.
    configuraciones = [
        {"model": "gpt-4o-mini",  "temp": 0.0},
        {"model": "gpt-4o",       "temp": 0.2},
        {"model": "gpt-4.1-mini", "temp": 0.1},
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
