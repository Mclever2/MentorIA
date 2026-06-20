"""Estado global del grafo multiagente de mentoría académica."""

from typing import List, Optional, Any, Dict
from typing_extensions import TypedDict


class ErrorRubrica(TypedDict):
    item_numero:    int
    puntaje_actual: int
    descripcion:    str


class MentoriaState(TypedDict):
    seccion_objetivo:       str
    contexto_recuperado:    str
    contexto_dependencias:  str
    contexto_teorico:       str

    rubrica_dinamica:       Optional[Any]

    max_iteraciones:        int

    plan_supervisor:        str

    texto_iterado:          str
    numero_iteracion:       int

    feedback_auditor:       str
    errores_rubrica:        List[ErrorRubrica]
    puntaje_estimado:       Optional[int]
    puntaje_previo:         Optional[float]
    meta_aprobacion:        Optional[float]
    items_mejorables:       Optional[List]
    items_na_tipo:          Optional[List]
    contexto_coherencia:    Optional[str]
    modo_nucleo:            Optional[bool]
    nucleo_plan:            Optional[Dict]
    redactor_solo_pulido:   Optional[bool]
    mejor_texto:            Optional[str]
    mejor_puntaje:          Optional[float]
    mejor_errores:          Optional[List]
    mejor_eval_final:       Optional[List]
    mejor_items_mejorables: Optional[List]

    observaciones_metodologicas: str

    resultado_consenso:     str
    resultado_disenso:      str
    iter_consenso:          int
    iter_disenso:           int

    debate_memory:          list
    debate_veredicto:       Optional[Dict]
    debate_completado:      bool
    historial_debate:       list

    siguiente_nodo:           str
    instrucciones_supervisor: str
    pasos_ejecutados:         int
    max_pasos_red:            int

    iter_auditada:            int
    iter_metodologica:        int

    _puntaje_max:             Optional[int]

    universidad:              str
    programa:                 str
    modalidad:                str
    perfil_institucional:     Optional[str]
    tipo_investigacion:       Optional[str]
    diseno:                   Optional[str]

    run_id:                   str
    puntaje_inicial:          Optional[float]

    consenso_matematico:      Optional[Dict]

    scores_subagentes:        Optional[List]
    consenso_matematico_auditor: Optional[Dict]

    loras_activas:            Optional[List]

    rutas_reportes:           Optional[List]

    consenso_ejecutado:       Optional[bool]
    disenso_ejecutado:        Optional[bool]
    auditor_ejecutado:        Optional[bool]
    metodologo_ejecutado:     Optional[bool]
    debate_ejecutado:         Optional[bool]

    redactor_evaluacion_rubrica: Optional[Dict]
    redactor_sugerencias_mejoras: Optional[str]
    historial_textos:            Optional[List[str]]
    # Nota de la RÚBRICA (auditor) en cada iteración de la red: [{iteracion, puntaje, maximo}].
    # La iteración es cosa de la red (rúbrica por defecto / subida); alimenta la trayectoria
    # que se muestra (NO el juez LLM, que solo corre inicial/final para el gain score).
    historial_puntajes_rubrica:  Optional[List[Dict]]
    evaluacion_upao_inicial:     Optional[List[Dict]]
    evaluacion_upao_final:       Optional[List[Dict]]


