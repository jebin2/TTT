import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)


async def require_api_key(api_key: str = Security(api_key_header)):
    if not settings.API_KEY:
        raise HTTPException(status_code=500, detail="TTT_API_KEY is not configured on the server")

    if not api_key or not secrets.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
