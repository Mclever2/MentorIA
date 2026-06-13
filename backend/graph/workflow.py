"""
Grafo multiagente de mentoría académica — ARQUITECTURA DE RED PURA.

Topología:
  START → nodo_supervisor ←────────────────────────────────────────────────────┐
               │  (conditional edge: lee state["siguiente_nodo"])              │
               ├──────────────→ nodo_redactor ───────────────────────────────┤ │
               ├──────────────→ nodo_auditor ────────────────────────────────┤ │
               ├──────────────→ nodo_metodologico ──────────────────────────┤ │
               ├──────────────→ nodo_debate ─────────────────────────────────┤ │
               │                  (panel de 4 subagentes + memoria compartida) │ │
               ├──────────────→ nodo_consenso ───────────────────────────────┤ │
               ├──────────────→ nodo_disenso ────────────────────────────────┘ │
               └──────────────→ END  (cuando siguiente_nodo == "fin")           │
  Todos los nodos regresan al Supervisor via edge fijo ───────────────────────┘

Protección anti-bucle:
  1. Semántica:  pasos_ejecutados >= max_pasos_red → Supervisor fuerza "fin"
  2. Sistémica:  recursion_limit = 80 supersteps (capa de seguridad de LangGraph)
"""

import os
import httpx
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from .state import MentoriaState
from .nodes import (
    make_nodo_supervisor,
    make_nodo_redactor,
    make_nodo_auditor,
    make_nodo_metodologico,
    make_nodo_debate,
    make_nodo_consenso,
    make_nodo_disenso,
    make_nodo_exportador,
)
from .edges import routing_supervisor

load_dotenv()

_raw_key = os.environ.get("OPENAI_API_KEY", "")
if _raw_key:
    os.environ["OPENAI_API_KEY"] = _raw_key.strip()

RECURSION_LIMIT = 80

_http_client = httpx.Client(
    timeout=httpx.Timeout(120.0, connect=30.0),
    limits=httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=60.0,
    ),
)


def _llm(temperatura: float = 0.3) -> ChatOpenAI:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "No se encontró 'OPENAI_API_KEY'. "
            "Configura tu .env con tu clave de OpenAI."
        )
    return ChatOpenAI(
        api_key=api_key,
        model="gpt-4o-mini",
        temperature=temperatura,
        max_retries=3,
        timeout=120.0,
        http_client=_http_client,
    )


def create_graph():
    """Construye y compila el StateGraph de red multiagente pura."""

    llm_supervisor   = _llm(temperatura=0.2)
    llm_redactor     = _llm(temperatura=0.4)
    llm_auditor      = _llm(temperatura=0.1)
    llm_metodologico = _llm(temperatura=0.2)
    llm_consenso     = _llm(temperatura=0.2)
    llm_disenso      = _llm(temperatura=0.2)

    builder = StateGraph(MentoriaState)

    builder.add_node("nodo_supervisor",   make_nodo_supervisor(llm_supervisor))
    builder.add_node("nodo_redactor",     make_nodo_redactor(llm_redactor))
    builder.add_node("nodo_auditor",      make_nodo_auditor(llm_auditor))
    builder.add_node("nodo_metodologico", make_nodo_metodologico(llm_metodologico))
    builder.add_node("nodo_debate",       make_nodo_debate(llm_auditor, llm_metodologico))
    builder.add_node("nodo_consenso",     make_nodo_consenso(llm_consenso))
    builder.add_node("nodo_disenso",      make_nodo_disenso(llm_disenso))
    builder.add_node("nodo_exportador",   make_nodo_exportador())

    builder.set_entry_point("nodo_supervisor")

    builder.add_conditional_edges(
        "nodo_supervisor",
        routing_supervisor,
        {
            "redactor":     "nodo_redactor",
            "auditor":      "nodo_auditor",
            "metodologico": "nodo_metodologico",
            "debate":       "nodo_debate",
            "consenso":     "nodo_consenso",
            "disenso":      "nodo_disenso",
            "fin":          "nodo_exportador",
        },
    )

    builder.add_edge("nodo_redactor",     "nodo_supervisor")
    builder.add_edge("nodo_auditor",      "nodo_supervisor")
    builder.add_edge("nodo_metodologico", "nodo_supervisor")
    builder.add_edge("nodo_debate",       "nodo_supervisor")
    builder.add_edge("nodo_consenso",     "nodo_supervisor")
    builder.add_edge("nodo_disenso",      "nodo_supervisor")
    builder.add_edge("nodo_exportador",   END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph


def get_run_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
