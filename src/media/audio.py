import base64

import httpx

from src.config.settings import settings
from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_audio(
    media_url: str | None,
    mimetype: str | None = None,
    media_base64: str | None = None,
) -> str:
    """
    Transcreve audio recebido via WhatsApp usando a API do OpenAI Whisper.

    Pipeline:
        1. Obtem os bytes do audio via base64 (UAZAPI envia no webhook) ou download
        2. Envio para a API de transcricao do OpenAI (whisper-1)
        3. Retorna o texto transcrito
    """
    if not settings.openai_api_key:
        logger.warning("AUDIO | OPENAI_API_KEY nao configurada, ignorando transcricao")
        return "[Transcricao indisponivel: OPENAI_API_KEY nao configurada]"

    # Obter bytes do audio: base64 (preferencial) ou download via URL
    audio_bytes = await _get_audio_bytes(media_url, media_base64)
    if not audio_bytes:
        return "[Audio recebido mas nao foi possivel obter o conteudo]"

    logger.info("AUDIO | Bytes obtidos | bytes=%d | Enviando para Whisper", len(audio_bytes))

    extension = _mime_to_extension(mimetype)
    filename = f"audio{extension}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"file": (filename, audio_bytes, mimetype or "audio/ogg")},
            data={"model": "whisper-1", "language": "pt"},
        )
        response.raise_for_status()
        result = response.json()

    transcript = result.get("text", "").strip()

    if not transcript:
        return "[Audio sem conteudo transcritivel]"

    logger.info("AUDIO | Transcricao concluida | chars=%d", len(transcript))
    return transcript


async def _get_audio_bytes(media_url: str | None, media_base64: str | None) -> bytes | None:
    """Obtem os bytes do audio: decodifica base64 ou faz download via URL."""
    if media_base64:
        try:
            logger.info("AUDIO | Decodificando base64 do webhook")
            return base64.b64decode(media_base64)
        except Exception as exc:
            logger.warning("AUDIO | Falha ao decodificar base64 | erro=%s", exc)

    if media_url:
        try:
            logger.info("AUDIO | Fazendo download via URL | url=%s", media_url[:80])
            uazapi = UazapiService()
            return await uazapi.download_media(media_url)
        except Exception as exc:
            logger.warning("AUDIO | Falha no download | erro=%s", exc)

    logger.warning("AUDIO | Nenhuma fonte de dados disponivel (sem base64 e sem URL)")
    return None


def _mime_to_extension(mimetype: str | None) -> str:
    """Mapeia MIME type para extensao de arquivo."""
    mapping = {
        "audio/ogg": ".ogg",
        "audio/ogg; codecs=opus": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".mp4",
        "audio/wav": ".wav",
        "audio/webm": ".webm",
        "audio/aac": ".aac",
        "audio/x-m4a": ".m4a",
    }
    if not mimetype:
        return ".ogg"
    return mapping.get(mimetype.lower(), ".ogg")
