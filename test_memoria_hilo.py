"""Prueba rápida (sin LLM) de la memoria del hilo: mejoras + confirmaciones."""

import sys

from backend.rag import cargar_modelo_embeddings, construir_vector_store
from api import registry, mejoras
from api.main import chat, ChatRequest
import api.intent as intent_mod

emb = cargar_modelo_embeddings()
paginas = [
    (1, "1.2 Objetivos\nEl objetivo general es analizar el rendimiento del sistema "
        "academico universitario en la region. " * 8),
    (2, "2.1 Marco teorico\nLas bases teoricas describen los modelos de evaluacion "
        "educativa y sus antecedentes relevantes. " * 8),
]
toc = {"1.2 Objetivos": 1, "2.1 Marco teorico": 2}
vs = construir_vector_store(paginas, toc, emb, collection_name="test_memoria")

doc = registry.registrar_documento(
    user_id="dev-local", nombre="test.pdf", pdf_hash="x1",
    vector_store=vs, estructura_toc=toc,
    stats=[{"seccion": "1.2 Objetivos", "pagina_inicio": 1, "chars": 100, "n_fragmentos": 2},
           {"seccion": "2.1 Marco teorico", "pagina_inicio": 2, "chars": 100, "n_fragmentos": 2}],
)

TEXTO_CORREGIDO = ("Objetivo general: Determinar la influencia del sistema multiagente "
                   "en la calidad de los proyectos de tesis de pregrado, periodo 2026.")
mejoras.registrar_resultado(doc, "1.2 Objetivos", {"texto_mejorado": TEXTO_CORREGIDO})
assert "1.2 Objetivos" in doc.evaluadas
assert mejoras.pendientes(doc) == ["1.2 Objetivos"]
print("OK 1 - registrar_resultado: seccion marcada como evaluada con mejora pendiente")

def fake_intent(mensaje, toc_nombres, contexto_previo="", hay_documento=False):
    if "objetivos" in mensaje.lower():
        return {"modo": "secciones", "secciones": ["1.2 Objetivos"], "respuesta": ""}
    return {"modo": "secciones", "secciones": ["2.1 Marco teorico"], "respuesta": ""}

intent_mod.interpretar_mensaje = fake_intent
sys.modules["api.intent"].interpretar_mensaje = fake_intent

USER = {"sub": "dev-local"}

r = chat(ChatRequest(mensaje="revisa mis objetivos", doc_id=doc.doc_id), user=USER)
assert r["tipo"] == "confirmacion" and r["subtipo"] == "reevaluar", r
print(f"OK 2 - reevaluar: '{r['mensaje'][:70]}...'")

r = chat(ChatRequest(mensaje="revisa mis objetivos", doc_id=doc.doc_id,
                     confirmar_reevaluacion=True), user=USER)
assert r["tipo"] == "run", r
print("OK 3 - reevaluar confirmado: crea el run sin preguntar por su propia mejora")

r = chat(ChatRequest(mensaje="revisa mi marco teorico", doc_id=doc.doc_id), user=USER)
assert r["tipo"] == "confirmacion" and r["subtipo"] == "aplicar_mejoras", r
print(f"OK 4 - aplicar_mejoras: '{r['mensaje'][:70]}...'")

n_antes = vs._collection.count()
r = chat(ChatRequest(mensaje="revisa mi marco teorico", doc_id=doc.doc_id,
                     decision_mejoras="aplicar"), user=USER)
assert r["tipo"] == "run" and r["mejoras_aplicadas"] == ["1.2 Objetivos"], r
assert mejoras.pendientes(doc) == []
print(f"OK 5 - mejora aplicada al vector store ({n_antes} → {vs._collection.count()} fragmentos)")

docs = vs.similarity_search("objetivo general investigacion", k=4)
contenidos = " ".join(d.page_content for d in docs)
assert "Determinar la influencia del sistema multiagente" in contenidos, contenidos[:300]
assert any(d.metadata.get("mejorado") for d in docs)
stats_obj = next(s for s in doc.stats if s["seccion"] == "1.2 Objetivos")
assert stats_obj.get("mejorado") is True
print("OK 6 - RAG recupera el texto corregido en lugar del original (PDF intacto)")

mejoras.registrar_resultado(doc, "2.1 Marco teorico", {"texto_mejorado": "Texto nuevo del marco."})
r = chat(ChatRequest(mensaje="revisa mis objetivos", doc_id=doc.doc_id,
                     confirmar_reevaluacion=True, decision_mejoras="mantener"), user=USER)
assert r["tipo"] == "run" and r["mejoras_aplicadas"] == [], r
assert mejoras.pendientes(doc) == ["2.1 Marco teorico"]
print("OK 7 - 'mantener original': el run corre sin modificar la memoria")

print("\nTODAS LAS PRUEBAS PASARON")
