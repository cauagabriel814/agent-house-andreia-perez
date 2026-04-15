"""
exchange.py - Node do fluxo de permuta (Feature 13).

Coleta dados do imovel atual do lead, aplica TAG lead_permuta e
transiciona para o fluxo de investidor para qualificar o imovel desejado.

Etapas (rastreadas por last_question):
  1. Primeira chamada (current_node != "exchange")
         -> TAG: origem_campanha (se UTM disponivel)
         -> EXCHANGE_INITIAL (pergunta sobre imovel atual)
         -> last_question = "exchange_imovel_atual"

  2. exchange_imovel_atual
         -> Extrai localizacao, tipo, suites e conservacao do imovel atual
         -> TAG: permuta_localizacao, permuta_tipo, permuta_suites,
                 permuta_conservacao, lead_permuta
         -> Envia INVESTOR_ASK_TIPO_NOME (o que o lead busca em troca)
         -> Transiciona para current_node = "investor"
         -> last_question = "investor_tipo_nome"
"""

import uuid

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.exchange import EXCHANGE_INITIAL
from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question,
)
from src.agent.prompts.investor import INVESTOR_ASK_TIPO_NOME
from src.agent.prompts.launch import SPECIFIC_ASK_EMPREENDIMENTO, SPECIFIC_INITIAL
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.kommo_service import KommoService
from src.services.tag_service import TagService
from src.utils.logger import logger

# ---------------------------------------------------------------------------
# Prompts para o LLM (extracao e classificacao)
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = (
    "Extraia o(a) {field} da seguinte mensagem do lead de forma concisa. "
    "Responda apenas com o valor extraido, sem explicacoes adicionais. "
    "Se a mensagem for uma pergunta, assunto completamente diferente, texto sem sentido, "
    "palavra aleatoria ou resposta claramente irrelevante para o campo solicitado, "
    "responda EXATAMENTE 'off_topic'. "
    "Se a informacao nao foi fornecida mas a mensagem e relevante ao contexto imobiliario, "
    "responda 'nao informado'.\n\n"
    "Mensagem: {message}"
)

_CLASSIFY_CONSERVACAO_PROMPT = (
    "Classifique o estado de conservacao do imovel na categoria correta. "
    "Estado informado: {valor}\n\n"
    "Categorias validas:\n"
    "- novo: Imovel novo ou nunca habitado\n"
    "- otimo: Em otimo estado, sem necessidade de reformas\n"
    "- bom: Bom estado, apenas manutencoes basicas\n"
    "- reforma: Necessita de reformas\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_TIPO_INTERESSE_PROMPT = (
    "O lead esta buscando um imovel especifico (que viu em anuncio) "
    "ou fazendo uma busca geral por imoveis?\n\n"
    "Categorias:\n"
    "- especifico: Menciona um empreendimento, endereco ou anuncio especifico\n"
    "- geral: Busca generica por imoveis sem mencionar algo especifico\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'especifico' ou 'geral'."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )


def _is_off_topic(value: str) -> bool:
    """Mensagem completamente fora do contexto (off_topic)."""
    return value.strip().lower() == "off_topic"


def _is_missing(value: str) -> bool:
    """Campo relevante mas nao fornecido — aceitar e seguir."""
    return value.strip().lower() in ("nao informado", "nao_informado")


async def _extract_field(message: str, field: str) -> str:
    """Usa LLM para extrair um campo especifico da resposta do lead."""
    llm = _get_llm()
    prompt = _EXTRACTION_PROMPT.format(field=field, message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip()


async def _classify_field(prompt_template: str, valor: str) -> str:
    """Usa LLM para classificar um valor em uma categoria pre-definida."""
    llm = _get_llm()
    prompt = prompt_template.format(valor=valor)
    response = await llm.ainvoke(prompt)
    return response.content.strip().lower()


async def _save_tag(lead_id: str | uuid.UUID | None, tags: dict, key: str, value: str) -> dict:
    """Persiste tag no banco e retorna o dict de tags atualizado."""
    tags_update = dict(tags)
    tags_update[key] = value
    if lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            await tag_svc.set_tag(lead_id, key, value)
    return tags_update


# ---------------------------------------------------------------------------
# Node principal
# ---------------------------------------------------------------------------


async def exchange_node(state: AgentState) -> dict:
    """
    Node: Fluxo de permuta com rastreamento de origem e coleta de dados (Feature 13).

    Consulte o docstring do modulo para detalhes de cada etapa.
    """
    phone = state["phone"]
    try:
        return await _exchange_node_impl(state)
    except Exception as exc:
        logger.exception("EXCHANGE | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("EXCHANGE | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "exchange"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _exchange_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    current_node = state.get("current_node", "")
    last_question = state.get("last_question")
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message
    tags = dict(state.get("tags") or {})
    utm_source = state.get("utm_source")
    kommo_contact_id = state.get("kommo_contact_id")
    kommo_lead_id = state.get("kommo_lead_id")
    reask_count = state.get("reask_count", 0)
    kommo = KommoService()
    last_bot_message = get_last_bot_message(state.get("messages") or [])

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if is_faq_question(effective_message):
        logger.info("EXCHANGE | FAQ detectado em fluxo ativo | phone=%s", phone)
        return {
            "current_node": "faq",
            "last_question": last_question,
            "awaiting_response": True,
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

    # Clarificação: lead pediu esclarecimento de uma pergunta já feita
    if last_question and is_clarification(effective_message):
        logger.info("EXCHANGE | Clarificacao detectada | lq=%s | phone=%s", last_question, phone)
        redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "exchange",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # -----------------------------------------------------------------------
    # Etapa 1: Primeira chamada (vinda do router)
    # Nota: se last_question já tem prefixo "exchange_", é retorno de FAQ — não reinicia.
    # -----------------------------------------------------------------------
    if current_node != "exchange" and not (last_question and last_question.startswith("exchange_")):
        logger.info("EXCHANGE | Iniciando fluxo de permuta | phone=%s", phone)

        # Salva UTM se disponível, mas sempre vai direto para dados do imóvel
        if utm_source:
            tags = await _save_tag(lead_id, tags, "origem_campanha", utm_source)
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            logger.info(
                "EXCHANGE | UTM rastreada: %r | phone=%s",
                utm_source,
                phone,
            )

        await send_whatsapp_message(phone, EXCHANGE_INITIAL)
        return {
            "current_node": "exchange",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "exchange_imovel_atual",
            "messages": [AIMessage(content=EXCHANGE_INITIAL)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2: Capturou origem (especifico ou geral)
    # -----------------------------------------------------------------------
    if last_question == "exchange_origem":
        logger.info("EXCHANGE | Classificando origem | phone=%s", phone)

        llm = _get_llm()
        tipo_resp = await llm.ainvoke(
            _TIPO_INTERESSE_PROMPT.format(message=effective_message)
        )
        tipo = tipo_resp.content.strip().lower()

        if "especifico" in tipo:
            logger.info(
                "EXCHANGE | Origem especifica -> perguntando empreendimento | phone=%s",
                phone,
            )
            await send_whatsapp_message(phone, SPECIFIC_ASK_EMPREENDIMENTO)
            return {
                "current_node": "exchange",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "exchange_empreendimento",
                "messages": [AIMessage(content=SPECIFIC_ASK_EMPREENDIMENTO)],
            }

        # Busca geral -> salvar origem e ir para dados do imovel
        tags = await _save_tag(lead_id, tags, "origem_campanha", "busca_geral")
        logger.info(
            "EXCHANGE | Origem geral -> salvando TAG e iniciando coleta do imovel | phone=%s",
            phone,
        )
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, EXCHANGE_INITIAL)
        return {
            "current_node": "exchange",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "exchange_imovel_atual",
            "messages": [AIMessage(content=EXCHANGE_INITIAL)],
        }

    # -----------------------------------------------------------------------
    # Etapa 3: Capturou nome do empreendimento especifico
    # -----------------------------------------------------------------------
    if last_question == "exchange_empreendimento":
        logger.info("EXCHANGE | Capturando nome do empreendimento | phone=%s", phone)

        empreendimento = await _extract_field(
            effective_message,
            "nome do empreendimento, imovel ou anuncio mencionado",
        )
        tags = await _save_tag(lead_id, tags, "origem_campanha", empreendimento)

        logger.info(
            "EXCHANGE | Empreendimento=%r -> iniciando coleta do imovel atual | phone=%s",
            empreendimento,
            phone,
        )
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, EXCHANGE_INITIAL)
        return {
            "current_node": "exchange",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "exchange_imovel_atual",
            "messages": [AIMessage(content=EXCHANGE_INITIAL)],
        }

    # -----------------------------------------------------------------------
    # Etapa 4: Capturou todos os dados do imovel (localizacao, tipo, suites, conservacao)
    # -----------------------------------------------------------------------
    if last_question == "exchange_imovel_atual":
        logger.info(
            "EXCHANGE | Capturando dados do imovel | phone=%s", phone
        )

        localizacao = await _extract_field(
            effective_message, "localizacao ou bairro do imovel atual"
        )

        if _is_off_topic(localizacao):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "exchange",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            localizacao = "nao informado"
        elif _is_missing(localizacao):
            localizacao = "nao informado"

        tipo = await _extract_field(
            effective_message,
            "tipo do imovel (apartamento, casa, cobertura, terreno, etc)",
        )
        suites = await _extract_field(
            effective_message, "quantidade de suites ou quartos do imovel"
        )
        conservacao_raw = await _extract_field(
            effective_message, "estado de conservacao do imovel"
        )
        conservacao = await _classify_field(
            _CLASSIFY_CONSERVACAO_PROMPT, conservacao_raw
        )

        tags = await _save_tag(lead_id, tags, "permuta_localizacao", localizacao)
        tags = await _save_tag(lead_id, tags, "permuta_tipo", tipo)
        tags = await _save_tag(lead_id, tags, "permuta_suites", suites)
        tags = await _save_tag(lead_id, tags, "permuta_conservacao", conservacao)
        tags = await _save_tag(lead_id, tags, "lead_permuta", "true")

        logger.info(
            "EXCHANGE | Localizacao=%r | Tipo=%r | Suites=%r | Conservacao=%r "
            "| TAG lead_permuta aplicada | Transicionando para investor | phone=%s",
            localizacao,
            tipo,
            suites,
            conservacao,
            phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        # Transiciona para o fluxo de investidor para qualificar o imovel desejado
        await send_whatsapp_message(phone, INVESTOR_ASK_TIPO_NOME)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_tipo_nome",
            "reask_count": 0,
            "messages": [AIMessage(content=INVESTOR_ASK_TIPO_NOME)],
        }

    # -----------------------------------------------------------------------
    # Fallback: estado desconhecido - reiniciar fluxo
    # -----------------------------------------------------------------------
    logger.warning(
        "EXCHANGE | Estado desconhecido last_question=%r | phone=%s",
        last_question,
        phone,
    )
    await send_whatsapp_message(phone, EXCHANGE_INITIAL)
    return {
        "current_node": "exchange",
        "awaiting_response": True,
        "last_question": "exchange_imovel_atual",
        "messages": [AIMessage(content=EXCHANGE_INITIAL)],
    }
