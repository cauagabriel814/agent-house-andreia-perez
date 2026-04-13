import httpx

from src.config.settings import settings
from src.utils.logger import logger


class UazapiService:
    """Client HTTP para a API da UAZAPI (WhatsApp)."""

    def __init__(self):
        self.base_url = settings.uazapi_base_url
        self.token = settings.uazapi_instance_id  # UAZAPI usa instance_id como token

    def _is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "token": self.token,
        }

    async def send_text_message(self, phone: str, message: str) -> dict:
        """Envia mensagem de texto via WhatsApp."""
        if not self._is_configured():
            logger.warning(
                "UAZAPI | Instancia nao configurada — mensagem nao enviada | phone=%s | preview=%s",
                phone,
                message[:60],
            )
            return {"status": "skipped", "reason": "uazapi_not_configured"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/send/text",
                    headers=self._headers(),
                    json={"number": phone, "text": message},
                )
                response.raise_for_status()
                logger.info(
                    "UAZAPI | Enviado | phone=%s | preview=%s",
                    phone,
                    message[:60].replace("\n", " "),
                )
                return response.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "UAZAPI | Falha ao enviar | phone=%s | status=%d | erro=%s",
                    phone,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                raise

    async def download_media(self, media_url: str) -> bytes:
        """Faz download de midia do WhatsApp."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(media_url, headers=self._headers())
                response.raise_for_status()
                logger.info("UAZAPI | Media baixada | url=%s | bytes=%d", media_url[:80], len(response.content))
                return response.content
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "UAZAPI | Falha ao baixar media | url=%s | status=%d",
                    media_url[:80],
                    exc.response.status_code,
                )
                raise
