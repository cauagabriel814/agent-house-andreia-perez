import uuid
from datetime import timedelta

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question_async,
)
from src.agent.prompts.launch import BUYER_FORA_PERFIL
from src.agent.prompts.sale import (
    SALE_ASK_ESTILO,
    SALE_ASK_PERGUNTAS_FINAIS,
    SALE_ASK_SUITES,
    SALE_ENCERRAMENTO_AGENDAMENTO,
    SALE_ENCERRAMENTO_SEM_VISITA,
    SALE_INITIAL,
    SALE_PROPOSTA_VISITA,
)
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.job_service import JobService
from src.services.kommo_service import KommoService
from src.services.tag_service import TagService
from src.utils.logger import logger

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

_WANTS_VISIT_PROMPT = (
    "O lead esta aceitando ou confirmando a visita tecnica ao imovel? "
    "Responda apenas 'sim' ou 'nao'.\n\n"
    "Mensagem: {message}"
)

_VALOR_ABAIXO_400K_PROMPT = (
    "O valor do imovel mencionado e inferior a R$ 400.000 (quatrocentos mil reais)? "
    "Considere qualquer mencao de valor, preco ou faixa de venda.\n\n"
    "Se o valor for inferior a R$ 400.000, responda 'sim'.\n"
    "Se o valor for R$ 400.000 ou superior, ou nao foi mencionado, responda 'nao'.\n\n"
    "Responda apenas 'sim' ou 'nao'.\n\n"
    "Mensagem: {message}"
)


async def _extract_field(message: str, field: str) -> str:
    """Usa LLM para extrair um campo especifico da resposta do lead."""
    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    prompt = _EXTRACTION_PROMPT.format(field=field, message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip()


async def _lead_wants_visit(message: str) -> bool:
    """Verifica se o lead quer agendar a visita tecnica."""
    llm = ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )
    prompt = _WANTS_VISIT_PROMPT.format(message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip().lower().startswith("sim")


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


async def sale_node(state: AgentState) -> dict:
    """
    Node: Fluxo de venda (proprietario) - Feature 10.

    Coleta dados do imovel em etapas progressivas via conversa natural,
    salva tags no banco e propoe visita tecnica gratuita de avaliacao.

    Etapas (rastreadas por last_question):
      1. Primeira chamada (current_node != "sale")
             -> Envia SALE_INITIAL (pergunta regiao)
             -> last_question = "sale_regiao"

      2. sale_regiao: extrai regiao, pergunta estilo
             -> TAG: localizacao_imovel_venda
             -> last_question = "sale_estilo"

      3. sale_estilo: extrai estilo, pergunta suites/diferenciais
             -> TAG: estilo_imovel
             -> last_question = "sale_suites"

      4. sale_suites: extrai suites/diferenciais, faz perguntas finais
             -> TAG: suites_diferenciais
             -> last_question = "sale_perguntas_finais"

      5. sale_perguntas_finais: extrai valor/prazo/exclusividade, seta TAG principal, propoe visita
             -> TAG: valor_esperado_venda, prazo_venda, aceita_exclusividade, proprietario_venda
             -> last_question = "sale_visita"

      6. sale_visita: processa resposta sobre visita, encerra fluxo
             -> TAG: visita_tecnica_solicitada
             -> TODO Feature 17: integrar Agenda Avaliador + CRM
    """
    phone = state["phone"]
    try:
        return await _sale_node_impl(state)
    except Exception as exc:
        logger.exception("SALE | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("SALE | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "sale"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _sale_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    lead_name = state.get("lead_name")
    current_node = state.get("current_node", "")
    last_question = state.get("last_question")
    current_message = state.get("current_message", "")
    processed_content = state.get("processed_content")
    effective_message = processed_content or current_message
    tags = dict(state.get("tags") or {})
    kommo_contact_id = state.get("kommo_contact_id")
    kommo_lead_id = state.get("kommo_lead_id")
    reask_count = state.get("reask_count", 0)
    kommo = KommoService()
    last_bot_message = get_last_bot_message(state.get("messages") or [])

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if await is_faq_question_async(effective_message):
        logger.info("SALE | FAQ detectado em fluxo ativo | phone=%s", phone)
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
        logger.info("SALE | Clarificacao detectada | lq=%s | phone=%s", last_question, phone)
        redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # ------------------------------------------------------------------
    # Etapa 1: Primeira chamada (vinda do router ou do generic)
    # Nota: se last_question já tem prefixo "sale_", é retorno de FAQ — não reinicia.
    # ------------------------------------------------------------------
    if current_node != "sale" and not (last_question and last_question.startswith("sale_")):
        logger.info("SALE | Iniciando fluxo de venda | phone=%s", phone)

        # Extrai regiao da mensagem que ativou o fluxo
        regiao_init = await _extract_field(effective_message, "regiao ou bairro do imovel")
        if _is_off_topic(regiao_init) or _is_missing(regiao_init):
            regiao_init = "nao informado"

        if regiao_init != "nao informado":
            tags = await _save_tag(lead_id, tags, "localizacao_imovel_venda", regiao_init)

        # Envia as mensagens de saudação (sem a pergunta de região)
        for part in SALE_INITIAL[:2]:
            await send_whatsapp_message(phone, part)
        ai_content = "\n\n".join(SALE_INITIAL)

        if regiao_init != "nao informado":
            logger.info(
                "SALE | Regiao=%r ja capturada na entrada | pulando para estilo | phone=%s",
                regiao_init, phone,
            )
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, SALE_ASK_ESTILO)
            return {
                "current_node": "sale",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "sale_estilo",
                "reask_count": 0,
                "messages": [AIMessage(content=ai_content), AIMessage(content=SALE_ASK_ESTILO)],
            }

        # Regiao não capturada — faz a pergunta normalmente
        await send_whatsapp_message(phone, SALE_INITIAL[2])
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "sale_regiao",
            "reask_count": 0,
            "messages": [AIMessage(content=ai_content)],
        }

    # ------------------------------------------------------------------
    # Etapa 2: Capturou regiao, perguntar sobre estilo
    # ------------------------------------------------------------------
    if last_question == "sale_regiao":
        logger.info("SALE | Capturando regiao | phone=%s", phone)

        regiao = await _extract_field(effective_message, "regiao ou bairro do imovel")

        if _is_off_topic(regiao):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "sale",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            regiao = "nao informado"
        elif _is_missing(regiao):
            regiao = "nao informado"

        tags = await _save_tag(lead_id, tags, "localizacao_imovel_venda", regiao)

        logger.info("SALE | Regiao extraida: %r | phone=%s", regiao, phone)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, SALE_ASK_ESTILO)
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "sale_estilo",
            "reask_count": 0,
            "messages": [AIMessage(content=SALE_ASK_ESTILO)],
        }

    # ------------------------------------------------------------------
    # Etapa 3: Capturou estilo, perguntar sobre suites e diferenciais
    # ------------------------------------------------------------------
    if last_question == "sale_estilo":
        logger.info("SALE | Capturando estilo | phone=%s", phone)

        estilo = await _extract_field(
            effective_message,
            "tipo ou estilo do imovel (casa, apartamento, cobertura, etc)",
        )

        if _is_off_topic(estilo):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "sale",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            estilo = "nao informado"
        elif _is_missing(estilo):
            estilo = "nao informado"

        tags = await _save_tag(lead_id, tags, "estilo_imovel", estilo)

        logger.info("SALE | Estilo extraido: %r | phone=%s", estilo, phone)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        for part in SALE_ASK_SUITES:
            await send_whatsapp_message(phone, part)
        ai_content = "\n\n".join(SALE_ASK_SUITES)
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "sale_suites",
            "reask_count": 0,
            "messages": [AIMessage(content=ai_content)],
        }

    # ------------------------------------------------------------------
    # Etapa 4: Capturou suites/diferenciais, fazer perguntas finais
    # ------------------------------------------------------------------
    if last_question == "sale_suites":
        logger.info("SALE | Capturando suites e diferenciais | phone=%s", phone)

        suites = await _extract_field(
            effective_message,
            "numero de suites e diferenciais do imovel (piscina, gourmet, etc)",
        )

        if _is_off_topic(suites):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "sale",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            suites = "nao informado"
        elif _is_missing(suites):
            suites = "nao informado"

        tags = await _save_tag(lead_id, tags, "suites_diferenciais", suites)

        logger.info("SALE | Suites/Diferenciais extraidos: %r | phone=%s", suites, phone)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        nome_prefixo = lead_name if lead_name else "Algumas perguntas"
        msg_perguntas = SALE_ASK_PERGUNTAS_FINAIS.format(nome_lead=nome_prefixo)
        await send_whatsapp_message(phone, msg_perguntas)
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "sale_perguntas_finais",
            "reask_count": 0,
            "messages": [AIMessage(content=msg_perguntas)],
        }

    # ------------------------------------------------------------------
    # Etapa 5: Capturou perguntas finais, setar TAG e propor visita
    # ------------------------------------------------------------------
    if last_question == "sale_perguntas_finais":
        logger.info(
            "SALE | Capturando perguntas finais e setando TAG proprietario_venda | phone=%s",
            phone,
        )

        valor = await _extract_field(effective_message, "expectativa de valor de venda do imovel")

        if _is_off_topic(valor):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "sale",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            valor = "nao informado"
        elif _is_missing(valor):
            valor = "nao informado"

        # Verificar se o valor esta abaixo de R$400k -> fora do perfil
        llm_check = ChatOpenAI(
            model="gpt-5.4", temperature=0, api_key=settings.openai_api_key, timeout=30
        )
        resp_400k = await llm_check.ainvoke(
            _VALOR_ABAIXO_400K_PROMPT.format(message=effective_message)
        )
        abaixo_400k = resp_400k.content.strip().lower().startswith("sim")

        if abaixo_400k:
            tags = await _save_tag(lead_id, tags, "lead_fora_perfil", "true")
            nome_display = lead_name or ""
            logger.info(
                "SALE | Imovel abaixo de R$400k | TAG: lead_fora_perfil | phone=%s", phone
            )
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            nome_prefix = f"{nome_display}, " if nome_display else ""
            msg_fora = BUYER_FORA_PERFIL.format(nome=nome_prefix)
            await send_whatsapp_message(phone, msg_fora)
            return {
                "current_node": "sale",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": False,
                "last_question": None,
                "reask_count": 0,
                "messages": [AIMessage(content=msg_fora)],
            }

        prazo = await _extract_field(effective_message, "prazo desejado para concluir a venda")
        exclusividade = await _extract_field(
            effective_message,
            "se o lead aceita exclusividade na venda (sim, nao ou talvez)",
        )

        tags = await _save_tag(lead_id, tags, "valor_esperado_venda", valor)
        tags = await _save_tag(lead_id, tags, "prazo_venda", prazo)
        tags = await _save_tag(lead_id, tags, "aceita_exclusividade", exclusividade)
        tags = await _save_tag(lead_id, tags, "proprietario_venda", "true")

        logger.info(
            "SALE | Valor=%r | Prazo=%r | Exclusividade=%r | phone=%s",
            valor,
            prazo,
            exclusividade,
            phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        nome_prefixo = f"{lead_name}, " if lead_name else ""
        msg_visita = SALE_PROPOSTA_VISITA.format(nome_lead=nome_prefixo)

        await send_whatsapp_message(phone, msg_visita)
        return {
            "current_node": "sale",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "sale_visita",
            "reask_count": 0,
            "messages": [AIMessage(content=msg_visita)],
        }

    # ------------------------------------------------------------------
    # Etapa 6: Processando resposta sobre a visita tecnica
    # ------------------------------------------------------------------
    if last_question == "sale_visita":
        logger.info(
            "SALE | Processando resposta sobre visita tecnica | phone=%s", phone
        )

        quer_visita = await _lead_wants_visit(effective_message)

        if quer_visita:
            tags = await _save_tag(lead_id, tags, "visita_tecnica_solicitada", "true")

            logger.info(
                "SALE | Lead confirmou visita tecnica | phone=%s | lead_id=%s",
                phone,
                lead_id,
            )

            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            stage_id = settings.kommo_stage_map_dict.get("avaliacao_agendada")
            if stage_id and kommo_lead_id:
                await kommo.update_lead_stage(kommo_lead_id, stage_id)

            # Agendar lembrete 24h antes da visita tecnica
            if lead_id:
                nome_display = state.get("lead_name") or "voce"
                async with async_session() as session:
                    job_svc = JobService(session)
                    await job_svc.schedule_after(
                        lead_id,
                        "reminder_24h_before",
                        timedelta(hours=24),
                        payload={
                            "name": nome_display,
                            "visit_type": "visita_tecnica",
                            "property_address": tags.get("localizacao", ""),
                        },
                    )
                logger.info("SALE | Job reminder_24h_before agendado | lead_id=%s", lead_id)

            await send_whatsapp_message(phone, SALE_ENCERRAMENTO_AGENDAMENTO)
            return {
                "current_node": "sale",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": False,
                "last_question": None,
                "reask_count": 0,
                "messages": [AIMessage(content=SALE_ENCERRAMENTO_AGENDAMENTO)],
            }
        else:
            tags = await _save_tag(lead_id, tags, "visita_tecnica_solicitada", "false")
            logger.info(
                "SALE | Lead nao quis agendar visita agora | phone=%s", phone
            )

            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, SALE_ENCERRAMENTO_SEM_VISITA)
            return {
                "current_node": "sale",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": False,
                "last_question": None,
                "reask_count": 0,
                "messages": [AIMessage(content=SALE_ENCERRAMENTO_SEM_VISITA)],
            }

    # ------------------------------------------------------------------
    # Fallback: estado desconhecido - reiniciar etapa de regiao
    # ------------------------------------------------------------------
    logger.warning(
        "SALE | Estado desconhecido last_question=%r | phone=%s", last_question, phone
    )
    for part in SALE_INITIAL:
        await send_whatsapp_message(phone, part)
    ai_content = "\n\n".join(SALE_INITIAL)
    return {
        "current_node": "sale",
        "awaiting_response": True,
        "last_question": "sale_regiao",
        "reask_count": 0,
        "messages": [AIMessage(content=ai_content)],
    }
