import base64

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.services.uazapi import UazapiService
from src.utils.logger import logger


async def process_image(media_url: str, mimetype: str | None = None) -> str:
    """
    Processa imagem recebida via WhatsApp usando OpenAI Vision (GPT-4o-mini).

    Pipeline:
        1. Download da imagem via UAZAPI
        2. Codificacao em base64
        3. Envio para o modelo Vision (gpt-4o-mini)
        4. Retorna descricao/transcricao do conteudo visual
    """
    if not media_url:
        return "[Imagem recebida sem URL de midia]"

    logger.info("IMAGE | Iniciando download | url=%s", media_url)
    uazapi = UazapiService()
    image_bytes = await uazapi.download_media(media_url)

    if not image_bytes:
        return "[Erro: imagem vazia ou inacessivel]"

    logger.info("IMAGE | Download concluido | bytes=%d | Enviando para Vision", len(image_bytes))

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_type = mimetype or "image/jpeg"

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
