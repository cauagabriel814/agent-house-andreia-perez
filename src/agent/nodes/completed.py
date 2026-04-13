from langchain_core.messages import AIMessage

from src.agent.prompts.completed import COMPLETED_HANDOFF
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.utils.logger import logger


async def completed_node(state: AgentState) -> dict:
    """
    Node: Conversa ja encerrada.

    Primeira mensagem pos-encerramento:
        - Envia COMPLETED_HANDOFF
        - Marca is_silenced=True
        - awaiting_response=False

    Mensagens subsequentes (is_silenced=True):
        - Nao responde nada
        - Log para auditoria
    """
    phone = state["phone"]
    is_silenced = state.get("is_silenced", False)

    if is_silenced:
        logger.info(
            "COMPLETED | Mensagem ignorada (lead ja silenciado) | phone=%s",
            phone,
        )
        return {
            "current_node": "completed",
            "is_silenced": True,
            "awaiting_response": False,
        }

    logger.info(
        "COMPLETED | Enviando handoff unico pos-encerramento | phone=%s",
        phone,
    )
    await send_whatsapp_message(phone, COMPLETED_HANDOFF)
    return {
        "current_node": "completed",
        "is_silenced": True,
        "awaiting_response": False,
        "messages": [AIMessage(content=COMPLETED_HANDOFF)],
    }
