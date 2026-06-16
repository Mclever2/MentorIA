"""
Configuraciones LoRA por agente e institución.

El profesor lo explicó con la analogía del actor:
  - Agente  = el actor (el LLM base, independiente)
  - LoRA    = el rol que asume (prompt especializado + foco temático)
  - MCP     = las fuentes de datos a las que se conecta (guiones / documentación)

El mismo agente evaluador se comporta diferente para UPAO vs UCB vs PAC porque:
  - Cada universidad tiene criterios distintos (LoRA diferente)
  - Cada universidad tiene documentación diferente (MCP apunta a Drive-folder distinto)

No es fine-tuning neuronal — es configuración de rol especializada por contexto,
exactamente lo que el profesor describió.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIGS_DIR = Path(__file__).parent / "university_configs"



TIPO_AUDITOR     = "auditor"
TIPO_METODOLOGO  = "metodologo"
TIPO_REDACTOR    = "redactor"
TIPO_DISENSO     = "disenso"



@dataclass
class LoraConfig:
    """
    Configuración de rol especializado para un subagente.

    Atributos:
        id:                 Identificador único (ej: "auditor_formal")
        rol:                Nombre descriptivo del rol
        enfasis:            Foco de evaluación (para logs y UI)
        prompt_modificador: Texto que se AGREGA al system prompt base del agente.
                            Define el "personaje" que asume el subagente.
        temperatura:        Temperatura del LLM. Menor = más determinístico.
        fuentes_datos:      Qué MCP tools puede usar ("biblioteca", "drive", "tesis")
        universidad_ctx:    Contexto institucional inyectado desde el YAML de la universidad.
                            Se completa por get_loras_para_agente().
        drive_folder_id:    ID de carpeta Drive de la universidad para este programa.
    """
    id:                 str
    rol:                str
    enfasis:            str
    prompt_modificador: str
    temperatura:        float
    fuentes_datos:      List[str] = field(default_factory=list)
    universidad_ctx:    str = ""
    drive_folder_id:    Optional[str] = None

    def system_prompt_completo(self, prompt_base: str) -> str:
        """Combina el prompt base del agente + el modificador LoRA + contexto de universidad."""
        partes = [prompt_base.strip()]
        if self.prompt_modificador:
            partes.append(f"\n\n---\n**ROL ESPECIALIZADO ({self.rol}):**\n{self.prompt_modificador.strip()}")
        if self.universidad_ctx:
            partes.append(f"\n\n---\n**CONTEXTO INSTITUCIONAL:**\n{self.universidad_ctx.strip()}")
        return "\n".join(partes)



_LORAS_BASE: dict[str, list[dict]] = {

    TIPO_AUDITOR: [
        {
            "id":    "auditor_formal",
            "rol":   "Auditor de Criterios Formales",
            "enfasis": "estructura formal, orden lógico y cumplimiento literal de rúbrica",
            "temperatura": 0.05,
            "fuentes_datos": ["biblioteca", "drive"],
            "prompt_modificador": (
                "Eres el evaluador más estricto del panel de auditoría. "
                "Tu única misión: detectar incumplimientos formales y estructurales con respecto a los criterios de la rúbrica. "
                "Evalúa cada ítem de forma literal. No hagas concesiones por 'intención' o 'contexto'. "
                "Si el ítem no está cumplido exactamente como lo exige la rúbrica, marca error. "
                "Sé conciso y específico en cada observación. "
                "Cuando hayas leído lo que dijeron los evaluadores anteriores del panel, "
                "identifica si hay criterios formales que ellos pasaron por alto."
            ),
        },
        {
            "id":    "auditor_equilibrado",
            "rol":   "Auditor Equilibrado",
            "enfasis": "balance entre rigor de rúbrica y comprensión del contexto",
            "temperatura": 0.15,
            "fuentes_datos": ["biblioteca", "drive", "tesis"],
            "prompt_modificador": (
                "Eres el evaluador equilibrado del panel. "
                "Aplicas los criterios de la rúbrica con el mismo rigor que exigen, "
                "pero reconoces el contexto y propósito del trabajo de investigación. "
                "Distingue errores críticos (que impiden aprobar el ítem) de aspectos mejorables (que requieren orientación). "
                "Cuando leas el historial del panel, complementa o matiza lo que dijeron los otros evaluadores "
                "aportando la perspectiva de balance."
            ),
        },
        {
            "id":    "auditor_contextual",
            "rol":   "Auditor de Coherencia Contextual",
            "enfasis": "coherencia global del texto con los objetivos del trabajo",
            "temperatura": 0.25,
            "fuentes_datos": ["tesis", "biblioteca"],
            "prompt_modificador": (
                "Eres el evaluador contextual del panel. "
                "Tu foco NO es la rúbrica ítem por ítem, sino la coherencia global: "
                "¿El texto, en su conjunto, cumple el propósito de la sección? "
                "¿La intención del autor es correcta aunque la forma pueda mejorarse? "
                "¿El texto es coherente con los objetivos e hipótesis del trabajo? "
                "Complementa lo dicho por los evaluadores anteriores del panel "
                "añadiendo la perspectiva de coherencia general que ellos pueden haber omitido."
            ),
        },
    ],

    TIPO_METODOLOGO: [
        {
            "id":    "metodologo_rigor",
            "rol":   "Metodólogo de Rigor Científico",
            "enfasis": "validez del diseño de investigación y corrección metodológica",
            "temperatura": 0.10,
            "fuentes_datos": ["biblioteca", "drive"],
            "prompt_modificador": (
                "Eres especialista en validación metodológica científica. "
                "Tu misión: verificar si el diseño de investigación es correcto. "
                "Preguntas clave que debes responder: "
                "¿El tipo de investigación (descriptiva, correlacional, experimental) es apropiado para los objetivos? "
                "¿Los métodos de recolección de datos son válidos para las variables declaradas? "
                "¿Hay errores en la operacionalización de variables? "
                "¿La muestra es representativa y el muestreo está justificado? "
                "Cita los principios metodológicos cuando detectes problemas (ej: Hernández Sampieri, Creswell)."
            ),
        },
        {
            "id":    "metodologo_coherencia",
            "rol":   "Metodólogo de Coherencia Transversal",
            "enfasis": "consistencia lógica entre todas las secciones del documento",
            "temperatura": 0.20,
            "fuentes_datos": ["tesis"],
            "prompt_modificador": (
                "Eres especialista en coherencia transversal de documentos de investigación. "
                "Tu misión: verificar si esta sección es consistente con el resto del trabajo. "
                "Preguntas clave: "
                "¿Las variables aquí mencionadas coinciden con las definidas en el planteamiento del problema? "
                "¿Los objetivos específicos de esta sección son alcanzables con la metodología declarada? "
                "¿Las hipótesis son coherentes con lo que se está analizando? "
                "¿Hay términos o conceptos usados de forma inconsistente entre secciones? "
                "Considera lo que dijo el evaluador de rigor científico y añade la perspectiva de coherencia cruzada."
            ),
        },
    ],

    TIPO_REDACTOR: [
        {
            "id":    "redactor_corrector",
            "rol":   "Redactor Corrector",
            "enfasis": "aplicar con precisión las correcciones del Auditor y Metodólogo",
            "temperatura": 0.30,
            "fuentes_datos": ["tesis"],
            "prompt_modificador": (
                "Eres un editor académico especializado en corrección dirigida. "
                "Tu misión: aplicar con precisión cada corrección señalada por el Auditor y el Metodólogo. "
                "Reglas estrictas: "
                "1. Cada párrafo modificado debe atender directamente a un error identificado. "
                "2. No agregues contenido que no resuelva un error específico. "
                "3. Mantén el registro académico formal del texto original. "
                "4. No elimines contenido correcto — solo corrige lo incorrecto. "
                "Genera la primera versión corregida del texto."
            ),
        },
        {
            "id":    "redactor_integrador",
            "rol":   "Redactor Integrador",
            "enfasis": "verificar coherencia y flujo del texto ya corregido",
            "temperatura": 0.40,
            "fuentes_datos": ["tesis"],
            "prompt_modificador": (
                "Eres un editor académico especializado en integración y coherencia. "
                "Recibirás la versión corregida por el Redactor Corrector (en el historial del panel). "
                "Tu misión: asegurarte de que las correcciones aplicadas no rompan el flujo ni la coherencia global. "
                "Verifica: "
                "1. ¿Las correcciones introducen inconsistencias terminológicas? "
                "2. ¿El argumento central del texto sigue siendo claro después de las correcciones? "
                "3. ¿El texto corregido fluye naturalmente o hay párrafos que quedaron 'pegados'? "
                "Produce la versión final integrada y coherente, manteniendo todas las correcciones válidas."
            ),
        },
    ],

    TIPO_DISENSO: [
        {
            "id":    "disenso_explicito",
            "rol":   "Detector de Conflictos Explícitos",
            "enfasis": "contradicciones directas y verificables entre evaluadores",
            "temperatura": 0.20,
            "fuentes_datos": [],
            "prompt_modificador": (
                "Eres un analista de conflictos explícitos entre evaluadores académicos. "
                "Tu misión: identificar contradicciones DIRECTAS y VERIFICABLES entre el Auditor (rúbrica) "
                "y el Metodólogo (rigor científico). "
                "Un conflicto explícito es: el Auditor dice X sobre el ítem N, el Metodólogo dice ¬X. "
                "Para cada conflicto: documenta qué dijo cada evaluador, por qué son incompatibles, "
                "y cuál es el impacto en la evaluación final. "
                "Sé factual — no interpretes ni inferas, solo reporta contradicciones evidentes."
            ),
        },
        {
            "id":    "disenso_estructural",
            "rol":   "Analista de Conflictos Estructurales",
            "enfasis": "desacuerdos de fondo, prioridades diferentes, tensiones implícitas",
            "temperatura": 0.30,
            "fuentes_datos": [],
            "prompt_modificador": (
                "Eres un analista de conflictos estructurales y de fondo en evaluaciones académicas. "
                "Más allá de las contradicciones obvias (ya identificadas por el detector explícito), "
                "tu misión es identificar tensiones de fondo: "
                "¿Los evaluadores tienen PRIORIDADES diferentes (rigor formal vs. rigor metodológico)? "
                "¿Hay una tensión entre lo que exige la rúbrica institucional y lo que requiere el método científico? "
                "¿Algún evaluador no está considerando el contexto institucional específico? "
                "¿Los criterios de los evaluadores son mutuamente excluyentes para este tipo de trabajo? "
                "Lee lo que reportó el detector explícito y profundiza con la dimensión estructural."
            ),
        },
    ],
}



@lru_cache(maxsize=16)
def _cargar_config_universidad(codigo: str) -> dict:
    """Carga y cachea el YAML de una universidad. Fallback: dict vacío."""
    archivo = _CONFIGS_DIR / f"{codigo.lower()}.yaml"
    if not archivo.exists():
        logger.warning(f"[LoRA] No existe config para universidad '{codigo}'. Usando defaults.")
        return {}
    with open(archivo, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _obtener_contexto_universidad(codigo: str, programa: str) -> tuple[str, Optional[str]]:
    """
    Retorna (contexto_institucional_completo, drive_folder_id) para un par universidad/programa.
    El contexto combina el texto general de la universidad + el énfasis del programa.
    """
    cfg = _cargar_config_universidad(codigo)
    if not cfg:
        return "", None

    ctx_base = cfg.get("contexto_institucional", "")

    import unicodedata
    prog_normalizado = (
        unicodedata.normalize("NFKD", programa.lower())
        .encode("ascii", "ignore")
        .decode()
        .replace(" ", "_")
        .replace("-", "_")
    )

    programas_cfg = cfg.get("programas", {})

    prog_cfg = programas_cfg.get(prog_normalizado, {})
    if not prog_cfg:
        for key, val in programas_cfg.items():
            if key in prog_normalizado or prog_normalizado in key:
                prog_cfg = val
                break

    enfasis = prog_cfg.get("enfasis_evaluacion", "")
    drive_folder_id = prog_cfg.get("drive_folder_id")

    ctx_completo = ctx_base
    if enfasis:
        ctx_completo = f"{ctx_base}\n\n**Énfasis específico del programa:**\n{enfasis}"

    return ctx_completo.strip(), drive_folder_id



def get_loras_para_agente(
    tipo_agente: str,
    universidad:  str = "upao",
    programa:     str = "ingeniería de sistemas",
    perfil_override: Optional[str] = None,
) -> list[LoraConfig]:
    """
    Retorna la lista de LoraConfig para el agente indicado,
    enriquecida con el contexto de la universidad y programa.

    Args:
        tipo_agente:  "auditor" | "metodologo" | "redactor" | "disenso"
        universidad:  Código de universidad (ej: "upao", "ucb", "pac")
        programa:     Nombre del programa académico
        perfil_override: Perfil institucional destilado de los reglamentos
                         (Tavily o documento subido). Si se pasa, reemplaza el
                         contexto del YAML estático — así los agentes adaptan su
                         personalidad a la universidad elegida por el estudiante.

    Returns:
        Lista de LoraConfig con universidad_ctx y drive_folder_id ya completados.
    """
    bases = _LORAS_BASE.get(tipo_agente)
    if not bases:
        logger.error(f"[LoRA] Tipo de agente desconocido: '{tipo_agente}'")
        return []

    if perfil_override and perfil_override.strip():
        ctx_universidad, drive_folder_id = perfil_override.strip(), None
    else:
        ctx_universidad, drive_folder_id = _obtener_contexto_universidad(universidad, programa)

    configs = []
    for b in bases:
        configs.append(LoraConfig(
            id=b["id"],
            rol=b["rol"],
            enfasis=b["enfasis"],
            prompt_modificador=b["prompt_modificador"],
            temperatura=b["temperatura"],
            fuentes_datos=list(b.get("fuentes_datos", [])),
            universidad_ctx=ctx_universidad,
            drive_folder_id=drive_folder_id,
        ))

    logger.debug(
        f"[LoRA] Agente '{tipo_agente}' | Universidad '{universidad}' | "
        f"Programa '{programa}' → {len(configs)} configs cargadas"
    )
    return configs
