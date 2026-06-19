"""
Verificación de JWT de Supabase.

El frontend envía el access_token de la sesión de Supabase en el header
Authorization: Bearer <token>. Supabase puede firmar los tokens de dos formas:

  • Asimétrica (ES256/RS256) — el sistema NUEVO de "signing keys". Se valida
    contra el JWKS público del proyecto:
        {SUPABASE_URL}/auth/v1/.well-known/jwks.json
  • HS256 (legacy) — secreto compartido en SUPABASE_JWT_SECRET.

Si no hay ni SUPABASE_URL ni SUPABASE_JWT_SECRET configurados, la API corre en
modo desarrollo sin autenticación (útil para pruebas locales).
"""

import os
import logging
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

SUPABASE_JWT_SECRET = (os.environ.get("SUPABASE_JWT_SECRET") or "").strip()
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")

# La auth está activa si hay forma de validar: JWKS (asimétrico) o secreto HS256.
_AUTH_ACTIVA = bool(SUPABASE_URL or SUPABASE_JWT_SECRET)


@lru_cache(maxsize=1)
def _jwks_client():
    """Cliente JWKS — cachea las claves públicas del proyecto Supabase."""
    import jwt

    url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    logger.info(f"[auth] Verificación asimétrica vía JWKS: {url}")
    return jwt.PyJWKClient(url)


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependencia FastAPI: devuelve el payload del JWT (sub = user_id de Supabase)."""
    if not _AUTH_ACTIVA:
        return {"sub": "dev-local", "email": "dev@local"}

    if credenciales is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autenticación.",
        )

    token = credenciales.credentials
    try:
        import jwt

        alg = jwt.get_unverified_header(token).get("alg", "")

        if alg.startswith(("ES", "RS", "PS")):
            # Firma asimétrica (signing keys nuevas de Supabase) → validar con JWKS.
            if not SUPABASE_URL:
                raise RuntimeError(
                    "Token con firma asimétrica pero falta la variable SUPABASE_URL."
                )
            clave = _jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                clave.key,
                algorithms=[alg],
                audience="authenticated",
            )
        else:
            # Legacy HS256 con secreto compartido.
            if not SUPABASE_JWT_SECRET:
                raise RuntimeError(
                    "Token HS256 pero falta la variable SUPABASE_JWT_SECRET."
                )
            payload = jwt.decode(
                token,
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
