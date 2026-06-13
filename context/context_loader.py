"""
ContextLoader — carga rúbricas y construye prompts de forma agnóstica a la universidad.

Principio: el código nunca menciona una universidad directamente.
Todo viene del contexto cargado desde ./rubrics/ (local), GCS o Google Drive.

Fuente seleccionada por variable de entorno CONTEXT_SOURCE:
  local   → ./rubrics/{key}.yaml  (defecto)
  gcs     → Google Cloud Storage
  gdrive  → Google Drive (URL pública)
"""

import os
import logging

logger = logging.getLogger(__name__)


class ContextLoader:
    def __init__(self):
        self.source = os.environ.get("CONTEXT_SOURCE", "local")

    def get(self, universidad: str, programa: str, modalidad: str = "tesis") -> dict:
        """Retorna el contexto completo para un par universidad+programa."""
        key = f"{universidad}_{programa}_{modalidad}".lower().replace(" ", "_")

        if self.source == "gcs":
            from .loaders.gcs_loader import cargar_gcs
            return cargar_gcs(key)
        elif self.source == "gdrive":
            from .loaders.gdrive_loader import cargar_gdrive
            return cargar_gdrive(key)
        else:
            from .loaders.local_loader import cargar_local
            return cargar_local(key)

    def construir_system_prompt_auditor(self, contexto: dict) -> str:
        criterios_texto = "\n".join(
            f"- {c['nombre']} (peso {c['peso']}): {c['descripcion']}"
            for c in contexto.get("criterios", [])
        )
        return (
            f"{contexto.get('instrucciones_auditor', '')}\n\n"
            f"Universidad: {contexto['universidad']}\n"
            f"Programa: {contexto['programa']}\n"
            f"Modalidad: {contexto['modalidad']}\n\n"
            f"Criterios de evaluación:\n{criterios_texto}\n\n"
            f"Escala: {contexto['escala_minima']} a {contexto['escala_maxima']}"
        )

    def construir_system_prompt_metodologo(self, contexto: dict) -> str:
        return (
            f"{contexto.get('instrucciones_metodologo', '')}\n\n"
            f"Universidad: {contexto['universidad']}\n"
            f"Programa: {contexto['programa']}"
        )
