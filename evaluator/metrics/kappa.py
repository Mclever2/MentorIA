from sklearn.metrics import cohen_kappa_score
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

_RAICES_ACUERDO = [
    "coincid", "correct", "valid", "acept", "confirm", "adecuad",
    "concuerd", "apropiад", "precis", "exact", "acertad", "pertinent",
    "suficient", "satisfactor", "complet", "coherent",
    "de acuerdo", "tiene razón", "comparto", "avalo", "respald",
    "bien planteado", "bien formulad", "bien definid", "bien estructur",
]

_RAICES_DESACUERDO = [
    "discrepo", "incorrect", "error", "invalid", "rechaz", "inadecuad",
    "inconsistent", "imprecis", "incomplet", "deficient", "ausent",
    "no cumple", "no es valid", "falt", "carec",
    "insuficient", "ambigu", "confus", "contradictor",
]


def _clasificar_turno(texto: str) -> int:
    texto_lower = texto.lower()
    score_acuerdo    = sum(1 for r in _RAICES_ACUERDO    if r in texto_lower)
    score_desacuerdo = sum(1 for r in _RAICES_DESACUERDO if r in texto_lower)
    return 1 if score_acuerdo > score_desacuerdo else 0


def calcular_kappa(historial_debate: list[str]) -> dict:
    """
    Calcula Cohen's Kappa sobre el historial del debate.
    Turnos pares = auditor, impares = metodólogo.
    Requiere mínimo 4 turnos (2 rondas completas) para ser significativo.
    """
    if len(historial_debate) < 2:
        return {
            "kappa": None,
            "nota": "debate insuficiente — se necesitan al menos 2 turnos"
        }

    turnos_auditor    = historial_debate[0::2]
    turnos_metodologo = historial_debate[1::2]
    min_turnos = min(len(turnos_auditor), len(turnos_metodologo))

    if min_turnos < 2:
        return {
            "kappa": None,
            "nota": "se necesitan al menos 2 rondas completas para calcular Kappa"
        }

    etiquetas_auditor    = [_clasificar_turno(turnos_auditor[i])    for i in range(min_turnos)]
    etiquetas_metodologo = [_clasificar_turno(turnos_metodologo[i]) for i in range(min_turnos)]

    if len(set(etiquetas_auditor)) == 1 or len(set(etiquetas_metodologo)) == 1:
        agente_sin_varianza = (
            "auditor" if len(set(etiquetas_auditor)) == 1 else "metodólogo"
        )
        return {
            "kappa": None,
            "nota": (
                f"Kappa indefinido — {agente_sin_varianza} clasificó todos los turnos igual "
                f"(sin varianza). No aplica la fórmula de Cohen."
            ),
            "turnos_analizados": min_turnos,
            "detalle": {
                "etiquetas_auditor":    etiquetas_auditor,
                "etiquetas_metodologo": etiquetas_metodologo,
            },
        }

    kappa = cohen_kappa_score(etiquetas_auditor, etiquetas_metodologo)
    return {
        "kappa": round(float(kappa), 4),
        "interpretacion": (
            "alto acuerdo entre agentes"      if kappa > 0.6
            else "acuerdo moderado"           if kappa > 0.2
            else "bajo acuerdo — debate activo o posiciones divergentes"
        ),
        "turnos_analizados": min_turnos,
        "detalle": {
            "etiquetas_auditor":    etiquetas_auditor,
            "etiquetas_metodologo": etiquetas_metodologo,
        }
    }
