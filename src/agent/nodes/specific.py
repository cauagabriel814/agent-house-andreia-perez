"""
specific.py - Node do fluxo de interesse especifico (Feature 14).

Processa leads oriundos de anuncios especificos ou com interesse de compra direta.
Rastreia a origem da campanha (UTM) e encaminha para o fluxo de comprador.

Etapas (rastreadas por last_question):
  1. Primeira chamada (current_node != "specific")
         -> Tenta extrair empreendimento da mensagem inicial
              SE encontrou:
                -> Verifica disponibilidade no catalogo
                -> Se indisponivel: avisa e encaminha para buyer
                -> Se disponivel: confirma com o lead ("E o X que voce quer?")
                -> last_question = "specific_confirma_empreendimento"
              SE nao encontrou:
                -> Verifica UTM -> TAG: origem_campanha (se presente)
                -> SPECIFIC_INITIAL (pergunta o que o lead procura)
                -> last_question = "specific_interesse"

  2. specific_confirma_empreendimento
         -> Lead confirma -> TAG: lead_imovel_especifico, situacao_imovel=lancamento
                         -> Transicao para launch: current_node = "launch"
         -> Lead nega    -> SPECIFIC_ASK_EMPREENDIMENTO
                         -> last_question = "specific_empreendimento"

  3. specific_interesse
         -> Extrai interesse (imovel especifico, lancamento, etc)
         -> TAG: lead_imovel_especifico (se for imovel especifico)
         -> Envia BUYER_ASK_TIPO (lancamento ou imovel pronto?)
         -> Transicao para buyer: current_node = "buyer", last_question = None
         -> awaiting_response = True
"""

import uuid

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question,
)
from src.agent.prompts.launch import (
    BUYER_ASK_TICKET,
    BUYER_ASK_TIPO,
    LAUNCH_ASK_NOME,
    SPECIFIC_ASK_EMPREENDIMENTO,
    SPECIFIC_INITIAL,
)
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.properties.catalog import search_properties
from src.services.kommo_service import KommoService
from src.services.tag_service import TagService
from src.utils.context_extractor import extract_context_from_message
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

_TIPO_INTERESSE_PROMPT = (
    "O lead esta buscando um imovel especifico (que viu em anuncio) "
    "ou fazendo uma busca geral por imoveis?\n\n"
    "Categorias:\n"
    "- especifico: Menciona um empreendimento, endereco ou anuncio especifico\n"
    "- geral: Busca generica por imoveis sem mencionar algo especifico\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'especifico' ou 'geral'."
)

_TIPO_IMOVEL_PROMPT = (
    "O lead menciona preferência por imóvel pronto para morar ou por lançamento?\n\n"
    "Categorias:\n"
    "- lancamento: Menciona lançamento, na planta, em construção, construtora\n"
    "- pronto: Menciona imóvel pronto, entrega imediata, pronto para morar\n"
    "- indefinido: Sem menção clara a nenhum tipo\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'lancamento', 'pronto' ou 'indefinido'."
)

_CONFIRMA_EMPREENDIMENTO_PROMPT = (
    "O lead está confirmando ou negando interesse no empreendimento *{empreendimento}*?\n\n"
    "Categorias:\n"
    "- confirmou: Lead confirma com 'sim', 'é esse', 'correto', 'exato', 'isso mesmo', "
    "ou qualquer confirmacao positiva\n"
    "- negou: Lead nega com 'não', 'não é esse', 'errado', 'outro'\n"
    "- off_topic: Resposta completamente fora do contexto\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'confirmou', 'negou' ou 'off_topic'."
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


async def _extract_field(message: str, field: str) -> str:
    """Usa LLM para extrair um campo especifico da resposta do lead."""
    llm = _get_llm()
    prompt = _EXTRACTION_PROMPT.format(field=field, message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip()


async def _save_tag(lead_id: str | uuid.UUID | None, tags: dict, key: str, value: str) -> dict:
    """Persiste tag no banco e retorna o dict de tags atualizado."""
    tags_update = dict(tags)
    tags_update[key] = value
    if lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            await tag_svc.set_tag(lead_id, key, value)
    return tags_update


def _is_off_topic(value: str) -> bool:
    """Mensagem completamente fora do contexto (off_topic)."""
    return value.strip().lower() == "off_topic"


def _is_missing(value: str) -> bool:
    """Campo relevante mas nao fornecido — aceitar e seguir."""
    return value.strip().lower() in ("nao informado", "nao_informado")


async def _check_enterprise_availability(empreendimento: str) -> bool:
    """Verifica se o empreendimento existe e esta disponivel no catalogo de lancamentos.

    Retorna True se disponivel ou se o catalogo estiver vazio (nao bloqueia o fluxo).
    """
    try:
        async with async_session() as session:
            props = await search_properties(lancamento=True, session=session)
        if not props:
            return True  # catalogo vazio -> nao bloquear
        nome = empreendimento.lower()
        return any(
            nome in p.get("empreendimento", "").lower()
            or p.get("empreendimento", "").lower() in nome
            for p in props
        )
    except Exception:
        return True  # em caso de erro -> nao bloquear


# ---------------------------------------------------------------------------
# Node principal
# ---------------------------------------------------------------------------


async def specific_node(state: AgentState) -> dict:
    """
    Node: Fluxo de interesse especifico (Feature 14).

    Consulte o docstring do modulo para detalhes de cada etapa.
    """
    phone = state["phone"]
    try:
        return await _specific_node_impl(state)
    except Exception as exc:
        logger.exception("SPECIFIC | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("SPECIFIC | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "specific"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _specific_node_impl(state: AgentState) -> dict:
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

    # Extração proativa: captura qualquer informação útil mencionada pelo lead
    tags = await extract_context_from_message(effective_message, tags, lead_id)

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if is_faq_question(effective_message):
        logger.info("SPECIFIC | FAQ detectado em fluxo ativo | phone=%s", phone)
        return {
            "current_node": "faq",
            "last_question": last_question,
            "awaiting_response": True,
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

    # -----------------------------------------------------------------------
    # Etapa 1: Primeira chamada (vinda do router)
    # Nota: se last_question já tem prefixo "specific_", é retorno de FAQ — não reinicia.
    # -----------------------------------------------------------------------
    if current_node != "specific" and not (last_question and last_question.startswith("specific_")):
        logger.info(
            "SPECIFIC | Iniciando fluxo de interesse especifico | phone=%s", phone
        )

        # Tenta extrair empreendimento da mensagem inicial para evitar perguntar 2x
        empreendimento_inicial = await _extract_field(
            effective_message,
            "nome de empreendimento, lancamento ou imovel especifico mencionado",
        )

        if not _is_off_topic(empreendimento_inicial) and not _is_missing(empreendimento_inicial):
            logger.info(
                "SPECIFIC | Empreendimento detectado na abertura: %r | phone=%s",
                empreendimento_inicial,
                phone,
            )

            # Verifica disponibilidade no catalogo antes de confirmar
            disponivel = await _check_enterprise_availability(empreendimento_inicial)

            if not disponivel:
                logger.info(
                    "SPECIFIC | Empreendimento %r indisponivel -> redirecionando | phone=%s",
                    empreendimento_inicial,
                    phone,
                )
                msg_indisponivel = (
                    f"Que bom que se interessou! 😊\n\n"
                    f"Infelizmente o *{empreendimento_inicial}* não está mais disponível "
                    f"em nosso portfólio no momento.\n\n"
                    f"Mas temos outros lançamentos incríveis que podem te interessar! "
                    f"Me conta o que você está buscando?"
                )
                await send_whatsapp_message(phone, msg_indisponivel)
                await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "awaiting_response": True,
                    "last_question": None,
                    "reask_count": 0,
                    "messages": [AIMessage(content=msg_indisponivel)],
                }

            # Disponivel: confirmar em vez de perguntar de novo
            tags = await _save_tag(lead_id, tags, "lead_imovel_especifico", empreendimento_inicial)
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            msg_confirma = (
                f"É o *{empreendimento_inicial}* que você ficou interessado(a)? 😊"
            )
            await send_whatsapp_message(phone, msg_confirma)
            return {
                "current_node": "specific",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "specific_confirma_empreendimento",
                "reask_count": 0,
                "messages": [AIMessage(content=msg_confirma)],
            }

        # Empreendimento nao detectado na abertura
        # Com UTM: origem ja conhecida -> ir direto para tipo (lancamento/pronto)
        if utm_source:
            tags = await _save_tag(lead_id, tags, "origem_campanha", utm_source)
            logger.info(
                "SPECIFIC | UTM rastreada: %r -> direto para tipo imovel | phone=%s",
                utm_source,
                phone,
            )
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, BUYER_ASK_TIPO)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": None,
                "reask_count": 0,
                "messages": [AIMessage(content=BUYER_ASK_TIPO)],
            }

        # Sem UTM: perguntar se viu anuncio especifico ou busca geral
        await send_whatsapp_message(phone, SPECIFIC_INITIAL)
        return {
            "current_node": "specific",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "specific_interesse",
            "reask_count": 0,
            "messages": [AIMessage(content=SPECIFIC_INITIAL)],
        }

    # -----------------------------------------------------------------------
    # Etapa 1b: Lead confirmou ou negou o empreendimento detectado
    # -----------------------------------------------------------------------
    if last_question == "specific_confirma_empreendimento":
        empreendimento = tags.get("lead_imovel_especifico", "")
        logger.info(
            "SPECIFIC | Verificando confirmacao do empreendimento %r | phone=%s",
            empreendimento,
            phone,
        )

        llm = _get_llm()
        confirma_resp = await llm.ainvoke(
            _CONFIRMA_EMPREENDIMENTO_PROMPT.format(
                empreendimento=empreendimento, message=effective_message
            )
        )
        confirma = str(confirma_resp.content).strip().lower()

        if "negou" in confirma:
            # Lead disse que é outro empreendimento -> perguntar qual
            logger.info("SPECIFIC | Lead negou empreendimento -> perguntando qual | phone=%s", phone)
            await send_whatsapp_message(phone, SPECIFIC_ASK_EMPREENDIMENTO)
            return {
                "current_node": "specific",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "specific_empreendimento",
                "reask_count": 0,
                "messages": [AIMessage(content=SPECIFIC_ASK_EMPREENDIMENTO)],
            }

        # Confirmou (ou off_topic -> beneficio da duvida) -> ir para launch
        logger.info(
            "SPECIFIC | Empreendimento %r confirmado -> launch | phone=%s",
            empreendimento,
            phone,
        )
        tags = await _save_tag(lead_id, tags, "situacao_imovel", "lancamento")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        nome_emp = empreendimento if empreendimento else "Este empreendimento"
        launch_msg = LAUNCH_ASK_NOME.format(empreendimento=nome_emp)
        await send_whatsapp_message(phone, launch_msg)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": None,
            "reask_count": 0,
            "messages": [AIMessage(content=launch_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2: Capturou interesse -> especifico ou geral?
    # -----------------------------------------------------------------------
    if last_question == "specific_interesse":
        logger.info(
            "SPECIFIC | Capturando interesse e tipo | phone=%s", phone
        )

        # Clarificação: lead não entendeu a pergunta — re-explica e aguarda
        if is_clarification(effective_message):
            logger.info("SPECIFIC | Clarificacao detectada | phone=%s", phone)
            redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
            await send_whatsapp_message(phone, redirect_msg)
            return {
                "current_node": "specific",
                "tags": tags,
                "last_question": last_question,
                "awaiting_response": True,
                "reask_count": reask_count,
            }

        llm = _get_llm()
        tipo_resp = await llm.ainvoke(
            _TIPO_INTERESSE_PROMPT.format(message=effective_message)
        )
        tipo = tipo_resp.content.strip().lower()

        if "especifico" in tipo:
            # Lead viu anuncio especifico -> perguntar qual empreendimento
            logger.info(
                "SPECIFIC | Interesse especifico -> perguntando empreendimento | phone=%s",
                phone,
            )
            await send_whatsapp_message(phone, SPECIFIC_ASK_EMPREENDIMENTO)
            return {
                "current_node": "specific",
                "tags": tags,
                "awaiting_response": True,
                "last_question": "specific_empreendimento",
                "reask_count": 0,
                "messages": [AIMessage(content=SPECIFIC_ASK_EMPREENDIMENTO)],
            }

        # Busca geral -> perguntar lancamento ou pronto (sempre, para confirmacao explicita)
        logger.info(
            "SPECIFIC | Interesse geral -> perguntando tipo de imovel | phone=%s",
            phone,
        )
        await send_whatsapp_message(phone, BUYER_ASK_TIPO)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": None,
            "reask_count": 0,
            "messages": [AIMessage(content=BUYER_ASK_TIPO)],
        }

    # -----------------------------------------------------------------------
    # Etapa 3: Capturou nome do empreendimento -> ticket
    # -----------------------------------------------------------------------
    if last_question == "specific_empreendimento":
        logger.info(
            "SPECIFIC | Capturando nome do empreendimento | phone=%s", phone
        )

        empreendimento = await _extract_field(
            effective_message,
            "nome do empreendimento, imovel ou anuncio mencionado",
        )

        if _is_off_topic(empreendimento):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "specific",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            empreendimento = "nao informado"
        elif _is_missing(empreendimento):
            empreendimento = "nao informado"

        tags = await _save_tag(lead_id, tags, "lead_imovel_especifico", empreendimento)
        tags = await _save_tag(lead_id, tags, "origem_campanha", empreendimento)

        logger.info(
            "SPECIFIC | Empreendimento=%r -> TAG lead_imovel_especifico + origem_campanha | phone=%s",
            empreendimento,
            phone,
        )

        # Empreendimento específico → sempre é lançamento: vai direto para launch_node
        tags = await _save_tag(lead_id, tags, "situacao_imovel", "lancamento")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        nome_emp = empreendimento if empreendimento != "nao informado" else "Este empreendimento"
        launch_msg = LAUNCH_ASK_NOME.format(empreendimento=nome_emp)
        await send_whatsapp_message(phone, launch_msg)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": None,
            "reask_count": 0,
            "messages": [AIMessage(content=launch_msg)],
        }

    # -----------------------------------------------------------------------
    # Fallback: estado desconhecido - reiniciar fluxo
    # -----------------------------------------------------------------------
    logger.warning(
        "SPECIFIC | Estado desconhecido last_question=%r | phone=%s",
        last_question,
        phone,
    )
    await send_whatsapp_message(phone, SPECIFIC_INITIAL)
    return {
        "current_node": "specific",
        "tags": tags,
        "awaiting_response": True,
        "last_question": "specific_interesse",
        "reask_count": 0,
        "messages": [AIMessage(content=SPECIFIC_INITIAL)],
    }
