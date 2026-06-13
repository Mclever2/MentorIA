from rouge_score import rouge_scorer
from sacrebleu.metrics import BLEU


def calcular_rouge(texto_referencia: str, texto_generado: str) -> dict:
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=False)
    scores = scorer.score(texto_referencia, texto_generado)
    return {
        "rouge1_f": round(scores["rouge1"].fmeasure, 4),
        "rouge2_f": round(scores["rouge2"].fmeasure, 4),
        "rougeL_f": round(scores["rougeL"].fmeasure, 4),
    }


def calcular_bleu(texto_referencia: str, texto_generado: str) -> dict:
    bleu = BLEU(effective_order=True)
    score = bleu.sentence_score(texto_generado, [texto_referencia])
    return {"bleu_score": round(score.score / 100, 4)}
