import base64

import httpx

from src.config.settings import settings
from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_audio(
    media_url: str | None,
    mimetype: str | None = None,
    media_base64: str | None = None,
    uazapi_message_id: str | None = None,
    chat_id: str = "",
) -> str:
    """
    Transcreve audio recebido via WhatsApp usando a API do OpenAI Whisper.

    Ordem de tentativa para obter os bytes:
      1. base64 inline do webhook
      2. Download via URL direta
      3. Download via API UAZAPI (POST /download/base64) usando messageId
    """
    if not settings.openai_api_key:
        logger.warning("AUDIO | OPENAI_API_KEY nao configurada, ignorando transcricao")
        return "[Transcricao indisponivel: OPENAI_API_KEY nao configurada]"

    audio_bytes, resolved_mimetype = await _get_media_bytes(
        media_base64, media_url, uazapi_message_id, chat_id, mimetype
    )

    if not audio_bytes:
        return "[Audio recebido mas nao foi possivel obter o conteudo]"

    effective_mimetype = resolved_mimetype or mimetype or "audio/ogg"
    logger.info("AUDIO | Bytes obtidos | bytes=%d | Enviando para Whisper", len(audio_bytes))

    extension = _mime_to_extension(effective_mimetype)
    filename = f"audio{extension}"

    # Prompt de contexto guia o Whisper a reconhecer melhor termos imobiliários,
    # bairros de Cuiabá/MT e padrões de fala informal em português brasileiro.
    _WHISPER_CONTEXT_PROMPT = (
        "Imóvel, Cuiabá, Mato Grosso, Várzea Grande, condomínio, suíte, suítes, cobertura, "
        "apartamento, casa, terreno, permuta, locação, financiamento, avaliação, exclusividade, "
        "Jardim das Américas, Coxipó, Goiabeiras, CPA, Bandeirantes, Duque de Caxias, "
        "Boa Esperança, Morada da Serra, Araés, Quilombo, Bairro Popular, Santa Rosa, "
        "lançamento, empreendimento, corretor, imobiliária, vistoria, escritura, ITBI, CRECI."
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"file": (filename, audio_bytes, effective_mimetype)},
            data={"model": "whisper-1", "language": "pt", "prompt": _WHISPER_CONTEXT_PROMPT},
        )
        response.raise_for_status()
        result = response.json()

    transcript = result.get("text", "").strip()
    if not transcript:
        return "[Audio sem conteudo transcritivel]"

    logger.info("AUDIO | Transcricao concluida | chars=%d", len(transcript))
    return transcript


async def _get_media_bytes(
    media_base64: str | None,
    media_url: str | None,
    uazapi_message_id: str | None,
    chat_id: str,
    mimetype: str | None,
) -> tuple[bytes | None, str | None]:
    """Tenta obter bytes da midia nas tres fontes disponiveis."""

    # 1. Base64 inline no webhook
    if media_base64:
        try:
            logger.info("AUDIO | Decodificando base64 inline do webhook")
            return base64.b64decode(media_base64), mimetype
        except Exception as exc:
            logger.warning("AUDIO | base64 invalido | erro=%s", exc)

    # 2. URL direta
    if media_url:
        try:
            logger.info("AUDIO | Baixando via URL direta | url=%s", media_url[:80])
            uazapi = UazapiService()
            data = await uazapi.download_media(media_url)
            if data:
                return data, mimetype
        except Exception as exc:
            logger.warning("AUDIO | Falha no download por URL | erro=%s", exc)

    # 3. API UAZAPI via messageId
    if uazapi_message_id:
        try:
            logger.info("AUDIO | Baixando via API UAZAPI | messageId=%s", uazapi_message_id)
            uazapi = UazapiService()
            data, resolved_mime = await uazapi.download_media_by_id(uazapi_message_id, chat_id)
            if data:
                return data, resolved_mime or mimetype
        except Exception as exc:
            logger.warning("AUDIO | Falha no download via API | erro=%s", exc)

    logger.warning(
        "AUDIO | Todas as fontes falharam | has_base64=%s | has_url=%s | has_msg_id=%s",
        bool(media_base64), bool(media_url), bool(uazapi_message_id),
    )
    return None, None


def _mime_to_extension(mimetype: str | None) -> str:
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
