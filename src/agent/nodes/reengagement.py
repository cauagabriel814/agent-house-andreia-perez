from src.agent.state import AgentState
from src.utils.logger import logger


async def reengagement_node(state: AgentState) -> dict:
    """
    Node: Reengajamento - lead retornou apos ausencia prolongada.

    Redefine o contador de timeout para zero, permitindo novo ciclo de
    qualificacao sem interferencia do historico de inatividade.

    Nota: este node e atingido quando o scheduler injeta um evento de
    reengajamento com message_type='reengagement'. No fluxo normal
    (lead responde apos timeout), route_entry ja encaminha para 'greeting'.
    """
    phone = state["phone"]
    lead_id = state.get("lead_id")
    prev_node = state.get("current_node", "?")
    timeout_count = state.get("timeout_count", 0)
    logger.info(
        "REENGAGEMENT | Lead reengajado | phone=%s | lead_id=%s | from=%s | timeouts=%d",
        phone,
        lead_id,
        prev_node,
        timeout_count,
    )

    return {
        "current_node": "reengagement",
        "timeout_count": 0,
        "awaiting_response": False,
    }
