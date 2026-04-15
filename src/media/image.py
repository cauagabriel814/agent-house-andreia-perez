import base64

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_image(
    media_url: str | None,
    mimetype: str | None = None,
    media_base64: str | None = None,
    uazapi_message_id: str | None = None,
    chat_id: str = "",
) -> str:
    """
    Processa imagem recebida via WhatsApp usando OpenAI Vision (GPT-4o-mini).

    Ordem de tentativa para obter os bytes:
      1. base64 inline do webhook
      2. Download via URL direta
      3. Download via API UAZAPI (POST /download/base64) usando messageId
    """
    image_b64, image_type = await _get_image_b64(
        media_base64, media_url, uazapi_message_id, chat_id, mimetype
    )

    if not image_b64:
        return "[Imagem recebida mas nao foi possivel obter o conteudo]"

    logger.info("IMAGE | Enviando para Vision | mimetype=%s", image_type)

    llm = ChatOpenAI(model="gpt-4o-mini", max_tokens=500)
    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": (
                    "Descreva esta imagem de forma completa e objetiva. "
                    "Se houver texto visivel, transcreva-o integralmente. "
                    "Se for um documento, extraia as informacoes principais. "
                    "Responda sempre em portugues."
                ),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_type};base64,{image_b64}",
                    "detail": "auto",
                },
            },
        ]
    )

    response = await llm.ainvoke([message])
    description = str(response.content).strip()

    if not description:
        return "[Imagem sem descricao gerada]"

    logger.info("IMAGE | Descricao gerada | chars=%d", len(description))
    return description


async def _get_image_b64(
    media_base64: str | None,
    media_url: str | None,
    uazapi_message_id: str | None,
    chat_id: str,
    mimetype: str | None,
) -> tuple[str | None, str]:
    """Retorna (base64_string, mimetype) tentando as tres fontes."""
    image_type = mimetype or "image/jpeg"

    # 1. Base64 inline no webhook
    if media_base64:
        try:
            base64.b64decode(media_base64)  # valida
            logger.info("IMAGE | Usando base64 inline do webhook")
            return media_base64, image_type
        except Exception as exc:
            logger.warning("IMAGE | base64 invalido | erro=%s", exc)

    # 2. URL direta
    if media_url:
        try:
            logger.info("IMAGE | Baixando via URL direta | url=%s", media_url[:80])
            uazapi = UazapiService()
            data = await uazapi.download_media(media_url)
            if data:
                return base64.b64encode(data).decode("utf-8"), image_type
        except Exception as exc:
            logger.warning("IMAGE | Falha no download por URL | erro=%s", exc)

    # 3. API UAZAPI via messageId
    if uazapi_message_id:
        try:
            logger.info("IMAGE | Baixando via API UAZAPI | messageId=%s", uazapi_message_id)
            uazapi = UazapiService()
            data, resolved_mime = await uazapi.download_media_by_id(uazapi_message_id, chat_id)
            if data:
                return base64.b64encode(data).decode("utf-8"), resolved_mime or image_type
        except Exception as exc:
            logger.warning("IMAGE | Falha no download via API | erro=%s", exc)

    logger.warning(
        "IMAGE | Todas as fontes falharam | has_base64=%s | has_url=%s | has_msg_id=%s",
        bool(media_base64), bool(media_url), bool(uazapi_message_id),
    )
    return None, image_type
