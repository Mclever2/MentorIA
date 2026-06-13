import json
import os

import requests
import yaml


def cargar_gdrive(key: str) -> dict:
    """
    Lee una rúbrica YAML desde Google Drive (URL pública).
    Variable de entorno: GDRIVE_RUBRIC_MAP = JSON con {key: file_id}

    Para archivos compartidos como 'cualquier persona con el enlace puede ver'.
    Para acceso restringido se necesita Service Account (deuda técnica pendiente).
    """
    gdrive_map = json.loads(os.environ.get("GDRIVE_RUBRIC_MAP", "{}"))

    if key not in gdrive_map:
        raise ValueError(f"No hay mapeo de Google Drive para: {key}")

    file_id = gdrive_map[key]
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return yaml.safe_load(response.text)
