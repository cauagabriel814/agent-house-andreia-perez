import asyncio
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import TECHNICAL_ERROR_MESSAGE, get_pending_topic
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.knowledge.vectorstore import search_knowledge
from src.utils.logger import logger

# Prefixos que indicam um fluxo ativo em andamento
_FLOW_QUESTION_PREFIXES = (
    "sale_",
    "rental_",
    "investor_",
    "exchange_",
    "specific_",
    "buyer_",
    "launch_",
)

_SYSTEM_PROMPT = (
    "Você é Andreia, consultora especialista da Residere Imóveis. "
    "Responda a pergunta do lead de forma clara, objetiva e amigável, "
    "usando APENAS as informações fornecidas no contexto abaixo. "
    "Se o contexto não contiver a informação necessária para responder à pergunta, "
    "responda APENAS com o texto exato: [SEM_INFORMACAO] — sem mais nada. "
    "Nunca invente informações. Use uma linguagem natural e próxima, com emojis quando adequado."
)

# Sentinel retornado pelo LLM quando não há informação suficiente no contexto
_SEM_INFORMACAO = "[SEM_INFORMACAO]"

# Pergunta exibida ao lead quando não temos a resposta
_SPECIALIST_CHOICE_MSG = (
    "Não encontrei essa informação aqui.\n\n"
    "Posso acionar um de nossos especialistas para te ajudar com isso — "
    "ele entraria em contato com você. O que prefere?\n\n"
    "*1. Quero falar com um especialista*\n"
    "*2. Prefiro continuar nossa conversa*"
)

_SPECIALIST_CONFIRMED_MSG = (
    "Perfeito! Já registrei seu pedido — um dos nossos especialistas vai entrar em contato "
    "com você em breve."
)

_CONTINUE_MSG = "Claro, sem problema!"

# Detecta resposta positiva (quer especialista)
_YES_RE = re.compile(
    r"\b(sim|s\b|ok|pode|quero|chama|liga|contata|especialista|manda|claro|1)\b",
    re.IGNORECASE,
)

# Detecta resposta negativa (quer continuar conversa)
_NO_RE = re.compile(
    r"\b(n[aã]o|nao|n\b|2|continua(r)?|segue|seguir|prefiro continuar|vamos continuar)\b",
    re.IGNORECASE,
)


async def faq_node(state: AgentState) -> dict:
    """
    Node: FAQ — responde dúvidas pontuais do lead via RAG (ChromaDB + text-embedding-3-small).

    Fluxo:
    1. Se last_question == "faq_specialist_choice": trata resposta do lead (especialista ou continuar)
    2. Caso normal: busca na knowledge base e gera resposta
    3. Se não há informação: pergunta ao lead se quer especialista ou continuar o fluxo
    """
    phone = state["phone"]
    last_question = state.get("last_question") or ""

    # --- Tratamento da resposta à escolha de especialista ---
    if last_question == "faq_specialist_choice":
        try:
            return await _handle_specialist_choice(state)
        except Exception as exc:
            logger.exception("FAQ | Erro ao tratar escolha de especialista | phone=%s | erro=%s", phone, str(exc))
            try:
                await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
            except Exception:
                pass
            return {
                "current_node": "faq",
                "last_question": state.get("last_question"),
                "awaiting_response": False,
            }

    # --- Fluxo normal de FAQ ---
    try:
        return await _faq_node_impl(state)
    except Exception as exc:
        logger.exception("FAQ | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("FAQ | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "faq"),
            "last_question": state.get("last_question"),
            "awaiting_response": state.get("awaiting_response", False),
        }


async def _faq_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    last_question = state.get("last_question") or ""
    current_message = state.get("current_message", "")
    question = state.get("processed_content") or current_message
    tags = dict(state.get("tags") or {})

    logger.info("FAQ | Dúvida recebida | phone=%s | pergunta=%r", phone, question[:80])

    # Busca na vector store (síncrono, executa em thread para não bloquear o loop)
    contexts: list[str] = await asyncio.to_thread(search_knowledge, question, 3)

    answer: str
    if contexts:
        context_text = "\n\n---\n\n".join(contexts)
        answer = await _generate_answer(question, context_text)
        logger.info("FAQ | Resposta gerada via RAG | phone=%s | tem_info=%s", phone, answer != _SEM_INFORMACAO)
    else:
        answer = _SEM_INFORMACAO
        logger.info("FAQ | Sem contexto na knowledge base | phone=%s", phone)

    # Não temos a informação → perguntar se quer especialista ou continuar
    if answer.strip() == _SEM_INFORMACAO:
        logger.info("FAQ | Sem informação disponível — oferecendo especialista | phone=%s", phone)

        # Salva estado para tratamento na próxima mensagem
        tags["_faq_original_lq"] = last_question
        tags["_faq_unanswered_q"] = question[:500]

        await send_whatsapp_message(phone, _SPECIALIST_CHOICE_MSG)

        return {
            "current_node": "faq",
            "last_question": "faq_specialist_choice",
            "awaiting_response": True,
            "tags": tags,
            "reask_count": 0,
            "messages": [AIMessage(content=_SPECIALIST_CHOICE_MSG)],
        }

    # Temos resposta — enviar normalmente
    await send_whatsapp_message(phone, answer)

    # Verifica se o lead estava no meio de um fluxo de qualificação
    has_active_flow = any(last_question.startswith(p) for p in _FLOW_QUESTION_PREFIXES)

    if has_active_flow:
        pending_topic = get_pending_topic(last_question)
        confirmation_msg = (
            f"Consegui esclarecer sua dúvida? 😊 "
            f"Quando estiver pronto, podemos continuar de onde paramos — "
            f"estava te perguntando sobre *{pending_topic}*."
        )
        logger.info(
            "FAQ | Fluxo ativo detectado (last_question=%r) - solicitando confirmação | phone=%s",
            last_question,
            phone,
        )
        await send_whatsapp_message(phone, confirmation_msg)

    return {
        "current_node": "faq",
        "last_question": last_question,  # preserva para retorno ao fluxo
        "awaiting_response": has_active_flow,
        "reask_count": 0,
        "messages": [AIMessage(content=answer)],
    }


async def _handle_specialist_choice(state: AgentState) -> dict:
    """Processa a resposta do lead à pergunta de especialista vs. continuar."""
    phone = state["phone"]
    current_message = state.get("current_message", "")
    tags = dict(state.get("tags") or {})

    # Recupera estado salvo antes da pergunta
    original_lq = tags.pop("_faq_original_lq", None) or ""
    unanswered_q = tags.pop("_faq_unanswered_q", "Dúvida não registrada")

    logger.info(
        "FAQ | Resposta à escolha de especialista | phone=%s | msg=%r | original_lq=%r",
        phone, current_message[:80], original_lq,
    )

    has_active_flow = any(original_lq.startswith(p) for p in _FLOW_QUESTION_PREFIXES)

    # Detecta intenção: quer especialista ou continuar?
    msg_clean = current_message.strip()
    is_no = bool(_NO_RE.search(msg_clean))
    is_yes = bool(_YES_RE.search(msg_clean)) and not is_no

    # Ambíguo → padrão: especialista (mais proativo para o negócio)
    wants_specialist = is_yes or not is_no

    if wants_specialist:
        # Envia notificação ao corretor/especialista
        await _send_specialist_notification(phone, state, unanswered_q)

        # Confirma ao lead
        reply = _SPECIALIST_CONFIRMED_MSG
        if has_active_flow:
            pending_topic = get_pending_topic(original_lq)
            reply += (
                f"\n\nEnquanto isso, posso continuar te ajudando. "
                f"Estava te perguntando sobre *{pending_topic}*."
            )
        await send_whatsapp_message(phone, reply)

        return {
            "current_node": "faq",
            "last_question": original_lq or None,
            "awaiting_response": has_active_flow,
            "tags": tags,
            "reask_count": 0,
            "messages": [AIMessage(content=reply)],
        }
    else:
        # Lead prefere continuar — redireciona ao fluxo
        reply = _CONTINUE_MSG
        if has_active_flow:
            pending_topic = get_pending_topic(original_lq)
            reply += f" Voltando para onde estávamos: estava te perguntando sobre *{pending_topic}*."
        else:
            reply += " Pode falar — o que mais posso te ajudar?"

        await send_whatsapp_message(phone, reply)

        return {
            "current_node": "faq",
            "last_question": original_lq or None,
            "awaiting_response": True,
            "tags": tags,
            "reask_count": 0,
            "messages": [AIMessage(content=reply)],
        }


async def _send_specialist_notification(phone: str, state: AgentState, unanswered_question: str) -> None:
    """Envia email ao corretor sobre dúvida que o FAQ não pôde responder."""
    try:
        from src.services.email_service import EmailService
        service = EmailService()
        lead_name = state.get("lead_name") or ""
        result = await service.send_faq_specialist_notification(
            lead_phone=phone,
            lead_name=lead_name,
            unanswered_question=unanswered_question,
        )
        if result.get("status") == "sent":
            logger.info("FAQ | Notificação de especialista enviada | phone=%s", phone)
        else:
            logger.warning(
                "FAQ | Notificação de especialista nao enviada | phone=%s | motivo=%s",
                phone, result.get("reason", result.get("status")),
            )
    except Exception as exc:
        logger.warning("FAQ | Falha ao enviar notificação de especialista | phone=%s | erro=%s", phone, str(exc))


async def _generate_answer(question: str, context: str) -> str:
    """Gera resposta usando ChatOpenAI com o contexto recuperado da knowledge base."""
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.3,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"**Contexto disponível:**\n{context}\n\n"
                f"**Pergunta do lead:** {question}"
            )
        ),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()
