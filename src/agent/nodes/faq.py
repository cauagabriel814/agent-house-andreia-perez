import asyncio

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
    "Se o contexto não contiver a resposta, diga que vai verificar com a equipe. "
    "Nunca invente informações. Use uma linguagem natural e próxima, com emojis quando adequado."
)

_FALLBACK_NO_CONTEXT = (
    "Ótima pergunta! Vou verificar essa informação com a equipe e te retorno em breve. 😊"
)


async def faq_node(state: AgentState) -> dict:
    """
    Node: FAQ - responde dúvidas pontuais do lead via RAG (ChromaDB + text-embedding-3-small).

    1. Busca trechos relevantes do documento de conhecimento (knowledge.docx)
    2. Usa ChatOpenAI para gerar resposta baseada no contexto encontrado
    3. Se não houver contexto relevante, envia mensagem de fallback
    4. Preserva last_question para retorno ao fluxo ativo
    """
    phone = state["phone"]
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

    logger.info("FAQ | Dúvida recebida | phone=%s | pergunta=%r", phone, question[:80])

    # Busca na vector store (síncrono, executa em thread para não bloquear o loop)
    contexts: list[str] = await asyncio.to_thread(search_knowledge, question, 3)

    if contexts:
        context_text = "\n\n---\n\n".join(contexts)
        answer = await _generate_answer(question, context_text)
        logger.info("FAQ | Resposta gerada via RAG | phone=%s", phone)
    else:
        answer = _FALLBACK_NO_CONTEXT
        logger.info("FAQ | Sem contexto na knowledge base - usando fallback | phone=%s", phone)

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
        # last_question preservado (não incluído no dict) para retorno ao fluxo
        "awaiting_response": has_active_flow,
        "reask_count": 0,  # Resetar: não penalizar o lead por ter feito uma pergunta FAQ
        "messages": [AIMessage(content=answer)],
    }


async def _generate_answer(question: str, context: str) -> str:
    """Gera resposta usando ChatOpenAI com o contexto recuperado da knowledge base."""
    llm = ChatOpenAI(
        model="gpt-5.4",
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
