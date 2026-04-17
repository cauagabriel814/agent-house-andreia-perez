import base64

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
        """Faz download de midia via URL direta."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(media_url, headers=self._headers())
                response.raise_for_status()
                logger.info("UAZAPI | Media baixada via URL | url=%s | bytes=%d", media_url[:80], len(response.content))
                return response.content
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "UAZAPI | Falha ao baixar media via URL | url=%s | status=%d",
                    media_url[:80],
                    exc.response.status_code,
                )
                raise

    async def download_media_by_id(
        self, message_id: str, chat_id: str = ""
    ) -> tuple[bytes | None, str | None]:
        """
        Baixa midia via API UAZAPI usando o messageId.

        Endpoint: POST {base_url}/message/download
        Body: {"id": "...", "return_base64": true, ...}
        Retorna: (bytes_da_midia, mimetype) ou (None, None) se falhar.
        """
        if not self._is_configured():
            logger.warning("UAZAPI | download_media_by_id: instancia nao configurada")
            return None, None

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/message/download",
                    headers=self._headers(),
                    json={
                        "id": message_id,
                        "return_base64": True,
                        "generate_mp3": False,
                        "return_link": False,
                        "transcribe": False,
                        "download_quoted": False,
                    },
                )
                response.raise_for_status()
                data = response.json()

                b64 = data.get("base64") or data.get("data") or data.get("file")
                mimetype = data.get("mimetype") or data.get("mediaType") or data.get("mime")

                if b64:
                    media_bytes = base64.b64decode(b64)
                    logger.info(
                        "UAZAPI | Media baixada via ID | messageId=%s | bytes=%d | mimetype=%s",
                        message_id,
                        len(media_bytes),
                        mimetype,
                    )
                    return media_bytes, mimetype

                logger.warning(
                    "UAZAPI | download_media_by_id: resposta sem base64 | messageId=%s | keys=%s",
                    message_id,
                    list(data.keys()),
                )
                return None, None

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "UAZAPI | Falha no download_media_by_id | messageId=%s | status=%d | body=%s",
                    message_id,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                return None, None
            except Exception as exc:
                logger.error(
                    "UAZAPI | Erro inesperado no download_media_by_id | messageId=%s | erro=%s",
                    message_id,
                    exc,
                )
                return None, None
