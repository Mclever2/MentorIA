"""
Servicio de perfil institucional por universidad.

Convierte reglamentos/lineamientos (encontrados con Tavily o subidos por el
estudiante) en un PERFIL destilado que ajusta la "personalidad" de los agentes:
NO es fine-tuning — es un modificador de comportamiento (contexto + énfasis) que
se inyecta en el system prompt vía get_loras_para_agente(perfil_override=...).

El mismo destilado sirve para la búsqueda web y para el documento subido, de modo
que los agentes no distinguen el origen (abstracción de proveedor de reglamento).
"""

import logging
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage

from backend.rag.extractor import extraer_texto_pdf
from backend.mcp.web_search import buscar_reglamentos
from .llm import llm_rapido, extraer_json

logger = logging.getLogger(__name__)

_MIN_CHARS = 200


class ReglamentoInvalido(ValueError):
    """El reglamento no es válido (vacío, sin relación o no procesable)."""


_PROMPT_DESTILAR = """Eres un experto en normativa académica universitaria. Recibes el texto de \
reglamentos/lineamientos de investigación de una universidad. Destila un PERFIL accionable que \
servirá para que agentes evaluadores de tesis adapten su criterio a ESA universidad. Sé concreto y \
específico: prefiere nombres de secciones exigidas, normas de citación, tipos de investigación \
admitidos, exigencias de muestra/instrumentos, etc. Evita generalidades vacías.

Responde SOLO JSON válido:
{{
  "es_reglamento": true|false,
  "coincide_universidad": true|false,
  "coincide_nivel": true|false,
  "nivel_detectado": "pregrado|maestría|doctorado|postgrado|desconocido",
  "contexto_institucional": "4-7 frases concretas: estructura/secciones que exige el proyecto, \
normas de citación y versión (APA 7, IEEE…), rigor metodológico esperado, formato y \
particularidades propias de esta universidad/programa. Cita lo que el texto realmente diga.",
  "enfasis": "5-8 viñetas (cada una inicia con '- ') con criterios ESPECÍFICOS y verificables que \
los evaluadores deben priorizar: secciones que el proyecto debe incluir, tipo/enfoque de \
investigación admitido, exigencias de población/muestra e instrumentos, norma y versión de \
citación, formato y cualquier criterio de la rúbrica institucional. Extrae solo lo que el texto \
respalde; NO inventes para llenar viñetas."
}}

Reglas de validación (importantes):
- "es_reglamento": false si el texto está vacío, es otra cosa o no tiene relación académica.
- "coincide_universidad": ¿el texto pertenece de verdad a la UNIVERSIDAD indicada abajo? Si es de \
otra universidad o genérico sin identificarla, pon false.
- "coincide_nivel": ¿el reglamento corresponde al NIVEL indicado (p. ej. pregrado vs postgrado/ \
maestría/doctorado)? Si el texto es de otro nivel, pon false e indica el real en "nivel_detectado".
Cuando es_reglamento sea false, deja contexto_institucional y enfasis vacíos.

UNIVERSIDAD: {universidad}  ·  PROGRAMA: {programa}  ·  NIVEL: {nivel}

TEXTO DE REGLAMENTOS:
{texto}
"""


def _a_texto(valor, vinetas: bool = False) -> str:
    """Normaliza un campo del LLM que puede venir como str o list[str]."""
    if isinstance(valor, list):
        items = [str(x).strip() for x in valor if str(x).strip()]
        if vinetas:
            return "\n".join(i if i.startswith("-") else f"- {i}" for i in items)
        return "\n".join(items)
    return str(valor or "").strip()


def _destilar(texto: str, universidad: str, programa: str, nivel: str, fuente: str) -> tuple[dict, dict]:
    """Llama al LLM para destilar el perfil. Devuelve (perfil, validacion).

    validacion = {coincide_universidad, coincide_nivel, nivel_detectado}.
    Valida relación/contenido (lanza ReglamentoInvalido si no es una rúbrica/reglamento).
    """
    muestra = (texto or "").strip()
    if len(muestra) < _MIN_CHARS:
        raise ReglamentoInvalido(
            "El reglamento parece vacío o demasiado corto. Sube un PDF nativo "
            "con los lineamientos de tu universidad."
        )

    try:
        resp = llm_rapido(temperatura=0.1).invoke([
            SystemMessage(content=_PROMPT_DESTILAR.format(
                universidad=universidad, programa=programa, nivel=nivel, texto=muestra[:14000],
            )),
            HumanMessage(content="Destila el perfil institucional."),
        ])
        data = extraer_json(resp.content)
    except Exception as exc:
        logger.error(f"[reglamento] Destilado LLM falló: {exc}")
        raise ReglamentoInvalido("No pude procesar el reglamento. Intenta de nuevo en unos segundos.")

    if not data or data.get("es_reglamento") is False:
        raise ReglamentoInvalido(
            "El documento no parece un reglamento o lineamiento académico. "
            "Sube las normas/lineamientos de tesis de tu universidad."
        )

    ctx = _a_texto(data.get("contexto_institucional"))
    enf = _a_texto(data.get("enfasis"), vinetas=True)
    if not ctx and not enf:
        raise ReglamentoInvalido("No se pudo extraer información útil del reglamento.")

    perfil = {
        "universidad":            universidad,
        "programa":               programa,
        "nivel":                  nivel,
        "contexto_institucional": ctx,
        "enfasis":                enf,
        "fuente":                 fuente,
    }
    validacion = {
        "coincide_universidad": bool(data.get("coincide_universidad", True)),
        "coincide_nivel":       bool(data.get("coincide_nivel", True)),
        "nivel_detectado":      str(data.get("nivel_detectado") or "").strip(),
    }
    return perfil, validacion


def perfil_desde_busqueda(universidad: str, programa: str, nivel: str) -> dict:
    """Busca reglamentos con Tavily y destila el perfil, validando universidad+nivel.

    Devuelve {ok, perfil?, motivo?}:
      - ok=False si no hay material o no corresponde a la universidad/nivel pedidos.
      - perfil puede incluir 'advertencia' si coincide la universidad pero no el nivel.
    """
    texto = buscar_reglamentos(universidad, nivel)
    if not texto:
        return {"ok": False, "motivo": f"No encontré reglamentos públicos de «{universidad}»."}

    try:
        perfil, val = _destilar(texto, universidad, programa, nivel, fuente="búsqueda web (Tavily)")
    except ReglamentoInvalido as exc:
        logger.info(f"[reglamento] Búsqueda sin material útil para '{universidad}': {exc}")
        return {"ok": False, "motivo": f"Lo que encontré de «{universidad}» no era un reglamento válido."}

    if not val["coincide_universidad"]:
        logger.info(f"[reglamento] Resultado no corresponde a '{universidad}' — descartado.")
        return {
            "ok": False,
            "motivo": f"Lo que encontré en la web no parece ser de «{universidad}». Súbelo manualmente.",
        }

    if not val["coincide_nivel"]:
        det = val["nivel_detectado"] or "otro nivel"
        perfil["advertencia"] = (
            f"El material público encontrado parece de nivel «{det}», no «{nivel}». "
            f"Si necesitas el de {nivel}, súbelo manualmente."
        )

    return {"ok": True, "perfil": perfil}


def _extraer_texto_archivo(nombre: str, contenido: bytes) -> str:
    """Extrae texto de un PDF (o .docx si python-docx está disponible)."""
    nombre = (nombre or "").lower()
    if nombre.endswith(".docx"):
        try:
            import io
            from docx import Document  # python-docx, opcional
            d = Document(io.BytesIO(contenido))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception as exc:
            raise ReglamentoInvalido(
                f"No pude leer el .docx ({exc}). Súbelo en PDF."
            )
    return extraer_texto_pdf(contenido)


def perfil_desde_documento(
    nombre: str, contenido: bytes, universidad: str, programa: str, nivel: str
) -> dict:
    """Destila el perfil desde un reglamento subido por el estudiante.

    Confía en la universidad/nivel elegidos por el usuario (él subió el archivo),
    pero añade una advertencia si el nivel del documento parece otro.
    """
    texto = _extraer_texto_archivo(nombre, contenido)
    perfil, val = _destilar(texto, universidad, programa, nivel, fuente=f"documento: {nombre}")
    if not val["coincide_nivel"] and val["nivel_detectado"]:
        perfil["advertencia"] = (
            f"El documento parece de nivel «{val['nivel_detectado']}», no «{nivel}». "
            "Lo usaré igual porque tú lo subiste."
        )
    return perfil
