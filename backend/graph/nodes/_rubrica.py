"""
Resolución de criterios de evaluación por sección — fuente única para los nodos.

Prioridad:
  1. Rúbrica subida por el estudiante (`state["rubrica_dinamica"]`, con `mapa_secciones`):
     se usan SOLO los ítems mapeados a la sección. Si la sección no tiene ítems
     mapeados → `aplica=False`: no se evalúa contra la rúbrica (no se inventan
     errores); se cae a criterios genéricos para dar orientación general.
  2. Rúbrica oficial UPAO (comportamiento histórico) vía SECCION_ITEMS_MAP.

Devuelve un dict con las dos formas que necesitan los nodos:
  - `tabla_md`      → tabla markdown (auditor)
  - `criterios_str` → lista "- Ítem N: descripción" (metodólogo / redactor)
"""

from __future__ import annotations

from ..state import MentoriaState


_CRITERIOS_GENERICOS = [
    "Claridad, coherencia y registro académico del texto.",
    "Rigor metodológico y consistencia con el resto del proyecto.",
    "Precisión conceptual y orden lógico de las ideas.",
]


def _generico() -> dict:
    from backend.config import ESCALA_MAX
    items = [{"numero": i + 1, "descripcion": d} for i, d in enumerate(_CRITERIOS_GENERICOS)]
    return {
        "items":        items,
        "items_nums":   [it["numero"] for it in items],
        "criterios_str": "\n".join(f"- {d}" for d in _CRITERIOS_GENERICOS),
        "tabla_md": (
            f"| N° | Criterio general | Puntaje (0-{ESCALA_MAX}) |\n"
            "|----|------------------|--------------|\n"
            + "\n".join(f"| {it['numero']:02d} | {it['descripcion']} | ___ |" for it in items)
        ),
        "puntaje_max": len(items) * ESCALA_MAX,
        "escala_max": ESCALA_MAX,
        "fuente": "criterios generales (tu rúbrica no contempla esta sección)",
        "aplica": False,
    }


def criterios_para_seccion(state: MentoriaState, seccion: str) -> dict:
    """Resuelve los criterios aplicables a `seccion`. Ver docstring del módulo."""
    rubrica = state.get("rubrica_dinamica")

    # NÚCLEO de coherencia: usa los ítems REALES de la rúbrica que cubren sus
    # secciones (título, problema, objetivos, hipótesis, variables, tipo/diseño,
    # población), precalculados en full_review. Evita los 3 criterios genéricos.
    plan = state.get("nucleo_plan") or {}
    if state.get("modo_nucleo") and plan.get("items"):
        from backend.config import ESCALA_MAX
        items = plan["items"]
        esc = ESCALA_MAX
        # Las IDs del juez son strings ('3.1'), así que NO uses tabla_items_markdown
        # (formatea con :02d y reventaría). El puntaje del núcleo no se usa para nota
        # (la nota real viene de la calificación); estos criterios solo GUÍAN al redactor.
        tabla = [f"| N° | Ítem de la Rúbrica | Puntaje (0-{esc}) |",
                 "|----|--------------------|--------------|"]
        for it in items:
            tabla.append(f"| {it.get('numero', '?')} | {it.get('descripcion', '')} | ___ |")
        return {
            "items":        items,
            "items_nums":   [it["numero"] for it in items],
            "criterios_str": "\n".join(
                f"- {it.get('descripcion', '')}" for it in items
            ),
            "tabla_md":     "\n".join(tabla),
            "puntaje_max":  len(items) * esc,
            "escala_max":   esc,
            "fuente":       "rúbrica del tipo — núcleo de coherencia",
            "aplica":       True,
        }

    if rubrica:
        from backend.rag.rubric_parser import (
            items_para_seccion,
            escala_max_rubrica,
            tabla_items_markdown,
        )
        items = items_para_seccion(rubrica, seccion)
        if not items:
            # Distinguir "rúbrica aún sin mapear" de "mapeada pero sección no contemplada".
            if not (rubrica.get("mapa_secciones")):
                items = list(rubrica.get("items", []))  # sin mapa → usar toda la rúbrica
            if not items:
                return _generico()
        esc = escala_max_rubrica(rubrica)
        return {
            "items":        items,
            "items_nums":   [it["numero"] for it in items],
            "criterios_str": "\n".join(
                f"- Ítem {it['numero']}: {it.get('descripcion', '')}" for it in items
            ),
            "tabla_md":     tabla_items_markdown(items, esc),
            "puntaje_max":  len(items) * esc,
            "escala_max":   esc,
            "fuente":       "rúbrica subida por el estudiante",
            "aplica":       True,
        }

    # Fallback histórico: rúbrica oficial UPAO.
    from backend.config import (
        _buscar_items_seccion,
        RUBRICA_ITEMS_UPAO,
        get_puntaje_maximo_seccion,
        ESCALA_MAX,
    )
    items_nums = _buscar_items_seccion(seccion)
    if not items_nums:
        return _generico()

    items = [{"numero": n, "descripcion": RUBRICA_ITEMS_UPAO.get(n, "")} for n in items_nums]
    lineas = [
        f"| N° | Ítem de la Rúbrica UPAO | Puntaje (0-{ESCALA_MAX}) |",
        "|----|-----------------------------|--------------|",
    ]
    for it in items:
        lineas.append(f"| {it['numero']:02d} | {it['descripcion']} | ___ |")
    return {
        "items":        items,
        "items_nums":   items_nums,
        "criterios_str": "\n".join(f"- Ítem {n}: {RUBRICA_ITEMS_UPAO.get(n, '')}" for n in items_nums),
        "tabla_md":     "\n".join(lineas),
        "puntaje_max":  get_puntaje_maximo_seccion(seccion),
        "escala_max":   ESCALA_MAX,
        "fuente":       "rúbrica oficial UPAO (por ítems)",
        "aplica":       True,
    }
