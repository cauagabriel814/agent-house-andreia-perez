import json

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE
from src.agent.prompts.human_fallback import (
    AI_FALLBACK_ESCALATE_MSG,
    HUMAN_FALLBACK_SYSTEM_PROMPT,
    HUMAN_FALLBACK_USER_TEMPLATE,
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

# Após este número de tentativas o agente escala para especialista
_MAX_FALLBACK_ATTEMPTS = 2


def _build_full_history(state: AgentState) -> str:
    """Constrói o histórico completo da conversa (sem limite de mensagens)."""
    history = state.get("conversation_history") or []
    lines = []
    for entry in history:
        role = "Lead" if entry.get("direction") == "in" else "Andreia"
        content = entry.get("processed_content") or entry.get("raw_content") or ""
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "Sem histórico anterior"


def _build_tags_info(state: AgentState) -> str:
    """Formata as tags coletadas para inclusão no prompt."""
    tags = state.get("tags") or {}
    if not tags:
        return "Nenhuma informação coletada ainda"
    return "\n".join(f"- {k}: {v}" for k, v in tags.items())


async def human_fallback_node(state: AgentState) -> dict:
    """
    Node: Agente de fallback com IA — simula consultora humana da Residere.

    Ativado quando o generic_node esgota as tentativas de identificar a intenção.
    Lê o histórico completo da conversa, responde de forma natural e tenta:
    - Identificar a intenção do lead para rotear ao fluxo correto
    - Extrair contexto útil (região, tipo de imóvel, etc.) para as tags
    - Escalar para especialista humano após _MAX_FALLBACK_ATTEMPTS tentativas

    Usa gpt-5.4 com JSON mode para retorno estruturado.
    """
    phone = state["phone"]
    try:
        return await _human_fallback_impl(state)
    except Exception as exc:
        logger.exception(
            "AI_FALLBACK | Erro inesperado | phone=%s | erro=%s", phone, str(exc)
        )
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception(
                "AI_FALLBACK | Falha ao enviar fallback | phone=%s", phone
            )
        return {
            "current_node": "ai_fallback",
            "last_question": state.get("last_question"),
            "awaiting_response": True,
        }


async def _human_fallback_impl(state: AgentState) -> dict:
    phone = state["phone"]
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message
    ai_fallback_count = state.get("ai_fallback_count") or 0

    logger.info(
        "AI_FALLBACK | Iniciando | phone=%s | tentativa=%d",
        phone,
        ai_fallback_count,
    )

    conversation_history = _build_full_history(state)
    tags_info = _build_tags_info(state)

    system_prompt = HUMAN_FALLBACK_SYSTEM_PROMPT.format(
        ai_fallback_count=ai_fallback_count,
    )
    user_content = HUMAN_FALLBACK_USER_TEMPLATE.format(
        conversation_history=conversation_history,
        tags_info=tags_info,
        current_message=effective_message,
    )

    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0.4,
        api_key=settings.openai_api_key,
        timeout=30,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    response = await llm.ainvoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )

    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.warning(
            "AI_FALLBACK | JSON inválido retornado pelo LLM | phone=%s | raw=%r | erro=%s",
            phone,
            response.content[:200],
            str(exc),
        )
        # Fallback: usa o conteúdo bruto como mensagem
        data = {
            "message": response.content.strip(),
            "identified_intent": None,
            "extracted_tags": {},
            "should_escalate": False,
        }

    message_to_send: str = data.get("message", "")
    identified_intent: str | None = data.get("identified_intent")
    extracted_tags: dict = data.get("extracted_tags") or {}
    should_escalate: bool = bool(data.get("should_escalate", False))

    # Validar intenção retornada
    if identified_intent not in _VALID_INTENTS:
        identified_intent = None

    # Mesclar tags extraídas com as tags já coletadas
    current_tags = dict(state.get("tags") or {})
    if extracted_tags:
        current_tags.update(extracted_tags)
        logger.info(
            "AI_FALLBACK | Tags extraídas | phone=%s | tags=%s",
            phone,
            extracted_tags,
        )

    new_fallback_count = ai_fallback_count + 1

    # --- Caso: escalada para especialista ---
    if should_escalate or ai_fallback_count >= _MAX_FALLBACK_ATTEMPTS:
        logger.info(
            "AI_FALLBACK | Escalando para especialista | phone=%s | tentativas=%d",
            phone,
            new_fallback_count,
        )
        # Envia a mensagem da IA (se houver) antes da mensagem de escalada
        if message_to_send:
            await send_whatsapp_message(phone, message_to_send)

        await send_whatsapp_message(phone, AI_FALLBACK_ESCALATE_MSG)
        return {
            "current_node": "completed",
            "awaiting_response": False,
            "detected_intent": identified_intent or "generico",
            "last_question": "ai_fallback_escalated",
            "ai_fallback_count": new_fallback_count,
            "tags": current_tags,
            "messages": [AIMessage(content=AI_FALLBACK_ESCALATE_MSG)],
        }

    # --- Caso: intenção identificada → envia mensagem e roteia imediatamente ---
    if identified_intent:
        logger.info(
            "AI_FALLBACK | Intenção identificada: %s — roteando para fluxo | phone=%s",
            identified_intent,
            phone,
        )
        await send_whatsapp_message(phone, message_to_send)
        return {
            "current_node": "ai_fallback",
            "awaiting_response": False,
            "detected_intent": identified_intent,
            "last_question": None,
            "ai_fallback_count": new_fallback_count,
            "tags": current_tags,
            "messages": [AIMessage(content=message_to_send)],
        }

    # --- Caso: sem intenção, continuar tentando ---
    logger.info(
        "AI_FALLBACK | Sem intenção identificada, aguardando resposta | phone=%s",
        phone,
    )
    await send_whatsapp_message(phone, message_to_send)
    return {
        "current_node": "ai_fallback",
        "awaiting_response": True,
        "detected_intent": "generico",
        "last_question": "ai_fallback_waiting",
        "ai_fallback_count": new_fallback_count,
        "tags": current_tags,
        "messages": [AIMessage(content=message_to_send)],
    }
