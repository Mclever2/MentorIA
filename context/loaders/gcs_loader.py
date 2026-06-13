import os

import yaml


def cargar_gcs(key: str) -> dict:
    """
    Lee una rúbrica YAML desde Google Cloud Storage.
    Requiere: pip install google-cloud-storage
    Variable de entorno: GCS_BUCKET_NAME
    Los archivos en GCS deben estar en: rubrics/{key}.yaml
    """
    from google.cloud import storage

    bucket_name = os.environ["GCS_BUCKET_NAME"]
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"rubrics/{key}.yaml")
    contenido = blob.download_as_text(encoding="utf-8")
    return yaml.safe_load(contenido)
