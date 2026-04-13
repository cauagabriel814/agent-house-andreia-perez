from fastapi import Request, HTTPException

from src.config.settings import settings


async def validate_webhook_token(request: Request):
    """Valida o token do webhook da UAZAPI."""
    token = request.headers.get("Authorization", "")
    if settings.webhook_secret and token != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Token invalido")
