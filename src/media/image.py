import base64

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_image(
    media_url: str | None,
    mimetype: str | None = None,
    media_base64: str | None = None,
) -> str:
    """
    Processa imagem recebida via WhatsApp usando OpenAI Vision (GPT-4o-mini).

    Pipeline:
        1. Obtem os bytes da imagem via base64 (UAZAPI envia no webhook) ou download
        2. Envio para o modelo Vision (gpt-4o-mini)
        3. Retorna descricao/transcricao do conteudo visual
    """
    # Obter base64 da imagem: direto do webhook ou via download
    image_b64, image_type = await _get_image_b64(media_url, mimetype, media_base64)
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
    media_url: str | None,
    mimetype: str | None,
    media_base64: str | None,
) -> tuple[str | None, str]:
    """Retorna (base64_string, mimetype) da imagem."""
    image_type = mimetype or "image/jpeg"

    if media_base64:
        logger.info("IMAGE | Usando base64 do webhook")
        try:
            base64.b64decode(media_base64)  # valida o base64
            return media_base64, image_type
        except Exception as exc:
            logger.warning("IMAGE | base64 invalido | erro=%s", exc)

    if media_url:
        try:
            logger.info("IMAGE | Fazendo download via URL | url=%s", media_url[:80])
            uazapi = UazapiService()
            image_bytes = await uazapi.download_media(media_url)
            if image_bytes:
                return base64.b64encode(image_bytes).decode("utf-8"), image_type
        except Exception as exc:
            logger.warning("IMAGE | Falha no download | erro=%s", exc)

    logger.warning("IMAGE | Nenhuma fonte de dados disponivel (sem base64 e sem URL)")
    return None, image_type
