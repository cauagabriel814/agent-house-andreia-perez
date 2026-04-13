from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.utils.logger import logger


async def active_listen_node(state: AgentState) -> dict:
    """
    Node: Escuta ativa - recebe a resposta do lead e prepara para classificacao de intencao.

    Responsabilidades:
    - Adicionar a mensagem atual ao historico de mensagens LangGraph
    - Marcar que nao estamos aguardando resposta
    - Preparar o state para o router classificar a intencao

    Fluxo:
        active_listen --> router (edge fixo)
    """
    phone = state["phone"]
    try:
        current_message = state.get("current_message", "")
        processed_content = state.get("processed_content")
        message_type = state.get("message_type", "text")

        # Usa conteudo processado (ex: transcricao de audio) se disponivel
        effective_message = processed_content or current_message

        logger.info(
            "ACTIVE_LISTEN | phone=%s | message_type=%s | content=%r",
            phone,
            message_type,
            effective_message[:80],
        )

        return {
            "current_node": "active_listen",
            "awaiting_response": False,
        }
    except Exception as exc:
        logger.exception("ACTIVE_LISTEN | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("ACTIVE_LISTEN | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", ""),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
        }
