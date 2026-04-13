import httpx

from src.config.settings import settings
from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_audio(media_url: str, mimetype: str | None = None) -> str:
    """
    Transcreve audio recebido via WhatsApp usando a API do OpenAI Whisper.

    Pipeline:
        1. Download do audio via UAZAPI
        2. Envio para a API de transcricao do OpenAI (whisper-1)
        3. Retorna o texto transcrito
    """
    if not media_url:
        return "[Audio recebido sem URL de midia]"

    if not settings.openai_api_key:
        logger.warning("AUDIO | OPENAI_API_KEY nao configurada, ignorando transcricao")
        return "[Transcricao indisponivel: OPENAI_API_KEY nao configurada]"

    logger.info("AUDIO | Iniciando download | url=%s", media_url)
    uazapi = UazapiService()
    audio_bytes = await uazapi.download_media(media_url)

    if not audio_bytes:
        return "[Erro: audio vazio ou inacessivel]"

    logger.info("AUDIO | Download concluido | bytes=%d | Enviando para Whisper", len(audio_bytes))

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
