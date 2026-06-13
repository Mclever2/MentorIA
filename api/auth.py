"""
Verificación de JWT de Supabase.

El frontend envía el access_token de la sesión de Supabase en el header
Authorization: Bearer <token>. Se valida con el JWT Secret del proyecto
(HS256). Si SUPABASE_JWT_SECRET no está configurado, la API corre en modo
desarrollo sin autenticación (útil para pruebas locales).
"""

import os
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

SUPABASE_JWT_SECRET = (os.environ.get("SUPABASE_JWT_SECRET") or "").strip()


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependencia FastAPI: devuelve el payload del JWT (sub = user_id de Supabase)."""
    if not SUPABASE_JWT_SECRET:
        return {"sub": "dev-local", "email": "dev@local"}

    if credenciales is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autenticación.",
        )

    try:
        import jwt

        payload = jwt.decode(
            credenciales.credentials,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except Exception as exc:
        logger.warning(f"[auth] Token inválido: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
        )
