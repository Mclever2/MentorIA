def calcular_gain_score(
    puntaje_inicial: float,
    puntaje_final: float,
    puntaje_maximo: float = 0.0,
) -> dict:
    """
    Gain Score de Hake (normalizado): mejora relativa al máximo posible.
    Fórmula: (score_post - score_pre) / (score_max - score_pre)
    Rango: (-∞, 1]. Negativo indica regresión; 1.0 indica mejora perfecta.
    """
    if puntaje_maximo <= 0:
        return {"gain_score": None, "nota": "puntaje máximo no disponible"}

    if puntaje_inicial == puntaje_final:
        return {
            "gain_score": 0.00,
            "puntaje_inicial": puntaje_inicial,
            "puntaje_final": puntaje_final,
            "interpretacion": "sin mejora detectada",
            "nota": "sin mejora detectada"
        }

    if puntaje_maximo == puntaje_inicial:
        return {"gain_score": 1.0, "nota": "puntaje inicial ya era máximo"}

    gain = (puntaje_final - puntaje_inicial) / (puntaje_maximo - puntaje_inicial)
    return {
        "gain_score": round(gain, 4),
        "puntaje_inicial": puntaje_inicial,
        "puntaje_final": puntaje_final,
        "interpretacion": (
            "mejora alta"     if gain > 0.6
            else "mejora moderada" if gain > 0.3
            else "mejora baja"     if gain > 0.0
            else "sin cambio"      if gain == 0.0
            else "regresión"
        ),
    }
