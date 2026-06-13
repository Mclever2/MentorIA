"""
Conector Google Drive — MCP para fuentes de datos institucionales.

El profesor lo describió así:
  "El MSP sirve para que usted se pueda conectar a diferentes fuentes de datos.
   Puedes conectarte a Drive, a bases de datos, a servicios web, etc."

Este conector permite que los subagentes accedan a rúbricas y documentos
institucionales almacenados en Google Drive, organizados por universidad y programa.

═══════════════════════════════════════════════════════════════
ESTRUCTURA DE CARPETAS RECOMENDADA EN DRIVE:
═══════════════════════════════════════════════════════════════

  Mentoría Académica/                    ← DRIVE_ROOT_FOLDER_ID
  ├── upao/
  │   ├── ingenieria_de_sistemas/
  │   │   ├── rubrica_principal.pdf      ← rúbrica oficial del programa
  │   │   ├── lineamientos_2023.pdf      ← lineamientos de investigación
  │   │   └── formato_tesis.docx
  │   └── pac/
  │       ├── rubrica_pac.pdf            ← rúbrica más detallada del PAC
  │       └── criterios_pac.pdf
  ├── ucb/
  │   └── ingenieria_de_sistemas/
  │       └── rubrica_ucb.pdf
  └── pac/
      └── ingenieria_de_sistemas/
          └── rubrica_pac_detallada.pdf

═══════════════════════════════════════════════════════════════
CONFIGURACIÓN — Variables de entorno en .env:
═══════════════════════════════════════════════════════════════

  DRIVE_CREDENTIALS_PATH = ./credentials/drive_service_account.json
  DRIVE_ROOT_FOLDER_ID   = 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74

═══════════════════════════════════════════════════════════════
CÓMO CONFIGURAR (guía al final de este archivo)
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import io
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CREDENTIALS_PATH = os.getenv("DRIVE_CREDENTIALS_PATH", "./credentials/drive_service_account.json")
_ROOT_FOLDER_ID   = os.getenv("DRIVE_ROOT_FOLDER_ID", "")

_EXTENSIONES_LEGIBLES = {".pdf", ".txt", ".md", ".docx"}


class DriveConnector:
    """
    Conector Google Drive para el sistema de mentoría académica.

    Permite a los subagentes buscar y leer documentos institucionales
    (rúbricas, lineamientos, criterios de evaluación) desde Drive,
    organizados por universidad y programa.

    Uso:
        connector = DriveConnector()
        if connector.disponible():
            rubrica = connector.obtener_rubrica("upao", "ingeniería de sistemas")
    """

    def __init__(self, credentials_path: str = _CREDENTIALS_PATH):
        self._credentials_path = credentials_path
        self._service = None
        self._intentar_inicializar()

    def _intentar_inicializar(self) -> None:
        """Intenta conectar con Drive. Si falla, el conector queda inactivo (no lanza excepción)."""
        if not Path(self._credentials_path).exists():
            logger.info(
                f"[Drive MCP] Credenciales no encontradas en '{self._credentials_path}'. "
                "Conector Drive inactivo — los subagentes usarán solo contexto local."
            )
            return
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/drive.readonly"]
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_path, scopes=scopes
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            logger.info("[Drive MCP] Conexión establecida con Google Drive.")
        except ImportError:
            logger.warning(
                "[Drive MCP] google-api-python-client no instalado. "
                "Instala con: pip install google-api-python-client google-auth"
            )
        except Exception as exc:
            logger.warning(f"[Drive MCP] No se pudo conectar a Drive: {exc}")

    def disponible(self) -> bool:
        """Retorna True si la conexión con Drive está activa."""
        return self._service is not None


    def _buscar_carpeta(self, nombre: str, parent_id: str) -> Optional[str]:
        """Busca una subcarpeta por nombre dentro de un folder padre. Retorna su ID o None."""
        if not self._service:
            return None
        try:
            query = (
                f"name='{nombre}' "
                f"and '{parent_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            result = (
                self._service.files()
                .list(q=query, fields="files(id, name)", pageSize=1)
                .execute()
            )
            archivos = result.get("files", [])
            return archivos[0]["id"] if archivos else None
        except Exception as exc:
            logger.warning(f"[Drive MCP] Error buscando carpeta '{nombre}': {exc}")
            return None

    def _listar_archivos_en_carpeta(self, folder_id: str) -> list[dict]:
        """Lista archivos en una carpeta (no subcarpetas)."""
        if not self._service:
            return []
        try:
            query = (
                f"'{folder_id}' in parents "
                f"and mimeType!='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            result = (
                self._service.files()
                .list(q=query, fields="files(id, name, mimeType)", pageSize=20)
                .execute()
            )
            return result.get("files", [])
        except Exception as exc:
            logger.warning(f"[Drive MCP] Error listando archivos: {exc}")
            return []

    def _leer_archivo_texto(self, file_id: str, nombre: str) -> str:
        """Lee el contenido de texto de un archivo Drive."""
        if not self._service:
            return ""
        ext = Path(nombre).suffix.lower()
        try:
            if ext == ".pdf":
                return self._leer_pdf_drive(file_id, nombre)
            elif ext in {".txt", ".md"}:
                return self._leer_texto_plano(file_id)
            elif ext == ".docx":
                return self._leer_docx_drive(file_id, nombre)
            else:
                response = (
                    self._service.files()
                    .export(fileId=file_id, mimeType="text/plain")
                    .execute()
                )
                return response.decode("utf-8") if isinstance(response, bytes) else str(response)
        except Exception as exc:
            logger.warning(f"[Drive MCP] No se pudo leer '{nombre}': {exc}")
            return ""

    def _leer_pdf_drive(self, file_id: str, nombre: str) -> str:
        """Descarga un PDF de Drive y extrae su texto con pdfplumber."""
        try:
            import pdfplumber
            from googleapiclient.http import MediaIoBaseDownload

            request = self._service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buffer.seek(0)
            paginas = []
            with pdfplumber.open(buffer) as pdf:
                for p in pdf.pages:
                    txt = p.extract_text()
                    if txt:
                        paginas.append(txt.strip())
            return "\n\n".join(paginas)
        except ImportError:
            logger.warning("[Drive MCP] pdfplumber no disponible para leer PDFs de Drive.")
            return f"[PDF '{nombre}' disponible en Drive pero no se pudo leer sin pdfplumber]"

    def _leer_texto_plano(self, file_id: str) -> str:
        from googleapiclient.http import MediaIoBaseDownload
        buffer = io.BytesIO()
        request = self._service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue().decode("utf-8", errors="replace")

    def _leer_docx_drive(self, file_id: str, nombre: str) -> str:
        try:
            import docx
            from googleapiclient.http import MediaIoBaseDownload
            buffer = io.BytesIO()
            request = self._service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buffer.seek(0)
            doc = docx.Document(buffer)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return f"[DOCX '{nombre}' en Drive — instala python-docx para leerlo]"


    def obtener_rubrica(
        self,
        universidad: str,
        programa: str,
        root_folder_id: str = _ROOT_FOLDER_ID,
    ) -> str:
        """
        Busca y retorna el contenido de la rúbrica institucional desde Drive.

        Navega la estructura: root → universidad → programa → archivos.
        Concatena el texto de todos los documentos encontrados.

        Args:
            universidad:    Código de universidad (ej: "upao", "ucb")
            programa:       Nombre del programa (ej: "ingeniería de sistemas")
            root_folder_id: ID de la carpeta raíz en Drive

        Returns:
            Texto de la rúbrica institucional, o "" si no se encuentra.
        """
        if not self._service or not root_folder_id:
            return ""

        import unicodedata
        prog_folder = (
            unicodedata.normalize("NFKD", programa.lower())
            .encode("ascii", "ignore")
            .decode()
            .replace(" ", "_")
        )

        logger.info(f"[Drive MCP] Buscando rúbrica: {universidad}/{prog_folder}")

        folder_univ = self._buscar_carpeta(universidad.lower(), root_folder_id)
        if not folder_univ:
            logger.info(f"[Drive MCP] Carpeta '{universidad}' no encontrada en Drive.")
            return ""

        folder_prog = self._buscar_carpeta(prog_folder, folder_univ)
        if not folder_prog:
            folder_prog = folder_univ
            logger.info(f"[Drive MCP] Carpeta del programa no encontrada — usando carpeta universidad.")

        archivos = self._listar_archivos_en_carpeta(folder_prog)
        if not archivos:
            logger.info(f"[Drive MCP] No hay archivos en la carpeta.")
            return ""

        textos = []
        for archivo in archivos:
            nombre = archivo["name"]
            ext = Path(nombre).suffix.lower()
            if ext not in _EXTENSIONES_LEGIBLES and "google-apps" not in archivo.get("mimeType", ""):
                continue
            contenido = self._leer_archivo_texto(archivo["id"], nombre)
            if contenido.strip():
                textos.append(f"[Documento Drive: {nombre}]\n{contenido.strip()}")
                logger.info(f"[Drive MCP] Leído: '{nombre}' ({len(contenido)} chars)")

        resultado = "\n\n---\n\n".join(textos)
        logger.info(
            f"[Drive MCP] Rúbrica institucional obtenida: "
            f"{len(textos)} documentos, {len(resultado)} chars total"
        )
        return resultado

    def buscar_documentos(self, query_texto: str, folder_id: str = _ROOT_FOLDER_ID) -> str:
        """
        Búsqueda full-text en Drive dentro de una carpeta.
        Útil para que los subagentes busquen referencias específicas.
        """
        if not self._service or not folder_id:
            return ""
        try:
            q = f"fullText contains '{query_texto}' and '{folder_id}' in parents and trashed=false"
            result = (
                self._service.files()
                .list(q=q, fields="files(id, name)", pageSize=5)
                .execute()
            )
            archivos = result.get("files", [])
            if not archivos:
                return ""
            textos = []
            for a in archivos[:3]:
                contenido = self._leer_archivo_texto(a["id"], a["name"])
                if contenido:
                    textos.append(f"[{a['name']}]\n{contenido[:2000]}")
            return "\n\n---\n\n".join(textos)
        except Exception as exc:
            logger.warning(f"[Drive MCP] Error en búsqueda: {exc}")
            return ""



_drive_connector: Optional[DriveConnector] = None


def get_drive_connector() -> DriveConnector:
    """Retorna la instancia singleton del DriveConnector."""
    global _drive_connector
    if _drive_connector is None:
        _drive_connector = DriveConnector()
    return _drive_connector


