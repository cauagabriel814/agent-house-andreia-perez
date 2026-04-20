from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.active_listen import INTENT_CLASSIFICATION_PROMPT
from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.prompts.generic import (
    GENERIC_EXPLANATION,
    GENERIC_RE_CLARIFY,
)
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.utils.logger import logger

_VALID_INTENTS = {
    "venda",
    "locacao",
    "investidor",
    "permuta",
    "interesse_especifico",
}

_INTENT_TO_NODE: dict[str, str] = {
    "venda": "sale",
    "locacao": "rental",
    "investidor": "investor",
    "permuta": "exchange",
    "interesse_especifico": "specific",
}


def _build_context(state: AgentState) -> str:
    """Constroi string de contexto com o historico recente da conversa."""
    history = state.get("conversation_history") or []
    recent = history[-6:] if len(history) > 6 else history
    lines = []
    for entry in recent:
        role = "Lead" if entry.get("direction") == "in" else "Andreia"
        content = entry.get("processed_content") or entry.get("raw_content") or ""
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "Sem historico anterior"


async def _classify_intent(message: str, context: str) -> str:
    """Usa LLM para re-classificar a intencao do lead."""
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    prompt = INTENT_CLASSIFICATION_PROMPT.format(
        message=message,
        context=context,
    )
    response = await llm.ainvoke(prompt)
    raw = response.content.strip().lower()
    first_token = raw.split()[0] if raw.split() else "generico"
    intent = first_token.strip("\"'.,;:")
    return intent if intent in (_VALID_INTENTS | {"generico"}) else "generico"


async def generic_node(state: AgentState) -> dict:
    """
    Node: Fluxo generico - explica servicos da Residere e recaptura a intencao.

    Primeira chamada (vinda do router com intencao=generico):
        - Envia mensagem explicando os servicos e opcoes
        - Define awaiting_response=True e last_question="generic_explanation"
        - Aguarda resposta do lead -> END

    Segunda chamada (lead respondeu; last_question="generic_explanation"):
        - Re-classifica a intencao com LLM usando a nova mensagem
        - Se intencao identificada: atualiza detected_intent e current_node
          -> route_after_generic encaminha para o fluxo correto (ex: sale)
        - Se continua generico: envia pergunta de clarificacao binaria -> END

    Terceira chamada (last_question="generic_re_clarify"):
        - Re-classifica novamente
        - Se intencao identificada: roteia para o fluxo correto
        - Se ainda generico: envia mensagem de encerramento e reinicia o fluxo
    """
    phone = state["phone"]
    try:
        return await _generic_node_impl(state)
    except Exception as exc:
        logger.exception("GENERIC | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("GENERIC | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", ""),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
        }


async def _generic_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    current_node = state.get("current_node", "")
    last_question = state.get("last_question")
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message

    # ------------------------------------------------------------------
    # Primeira chamada: vinda do router (current_node era "router")
    # ------------------------------------------------------------------
    if current_node != "generic":
        logger.info(
            "GENERIC | Primeira chamada - enviando explicacao | phone=%s", phone
        )
        await send_whatsapp_message(phone, GENERIC_EXPLANATION)
        return {
            "current_node": "generic",
            "awaiting_response": True,
            "detected_intent": "generico",
            "last_question": "generic_explanation",
            "messages": [AIMessage(content=GENERIC_EXPLANATION)],
        }

    # ------------------------------------------------------------------
    # Segunda e terceira chamada: lead respondeu, re-classificar intencao
    # ------------------------------------------------------------------
    logger.info(
        "GENERIC | Re-classificando intencao | phone=%s | last_question=%s | message=%r",
        phone,
        last_question,
        effective_message[:80],
    )

    intent = await _classify_intent(effective_message, _build_context(state))

    if intent in _VALID_INTENTS:
        target_node = _INTENT_TO_NODE[intent]
        logger.info(
            "GENERIC | Intencao identificada: %s -> %s | phone=%s",
            intent,
            target_node,
            phone,
        )
        # Mantemos current_node="generic" para que os flow nodes detectem
        # corretamente a primeira chamada via `if current_node != "sale"` etc.
        # route_after_generic usa detected_intent para rotear, nao current_node.
        return {
            "current_node": "generic",
            "detected_intent": intent,
            "awaiting_response": False,
            "last_question": None,
        }

    # Ainda generico apos re-clarificacao: acionar agente de fallback com IA
    if last_question == "generic_re_clarify":
        logger.info(
            "GENERIC | Intencao nao identificada apos duas tentativas - acionando ai_fallback | phone=%s",
            phone,
        )
        return {
            "current_node": "generic",
            "awaiting_response": False,
            "detected_intent": "generico",
            "last_question": "generic_give_up",
        }

    # Segunda tentativa: enviar pergunta de clarificacao binaria
    logger.info(
        "GENERIC | Intencao nao identificada - enviando re-clarificacao | phone=%s",
        phone,
    )
    await send_whatsapp_message(phone, GENERIC_RE_CLARIFY)
    return {
        "current_node": "generic",
        "awaiting_response": True,
        "detected_intent": "generico",
        "last_question": "generic_re_clarify",
        "messages": [AIMessage(content=GENERIC_RE_CLARIFY)],
    }
