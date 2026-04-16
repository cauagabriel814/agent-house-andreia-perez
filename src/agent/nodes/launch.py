"""
launch.py - Node do fluxo de lancamento imobiliario (Feature 14).

Qualifica leads interessados em lancamentos, coleta dados completos,
calcula score e agenda apresentacao ou envia material completo.

Este node e ativado pelo buyer_node, que enviou LAUNCH_ASK_NOME
e configurou current_node = "launch", last_question = None.
A deteccao de "primeira chamada" usa last_question is None.

Etapas (rastreadas por last_question):
  1. last_question is None (vindo do buyer)
         -> Extrai nome -> TAG: lead_lancamento_identificado, lead_identificado
         -> LAUNCH_APRESENTAR (apresenta empreendimento)
         -> last_question = "launch_regiao"

  2. launch_regiao
         -> Verifica se conhece a regiao
         -> TAG: conhece_regiao_lancamento
         -> LAUNCH_CONHECE_SIM | LAUNCH_CONHECE_NAO + LAUNCH_ASK_PLANTA
         -> last_question = "launch_planta"

  3. launch_planta
         -> Extrai tipo de unidade -> TAG: planta_interesse
         -> LAUNCH_ASK_PAGAMENTO
         -> last_question = "launch_pagamento"

  4. launch_pagamento
         -> Extrai forma de pagamento -> TAG: forma_pagamento_lancamento
         -> LAUNCH_ASK_URGENCIA
         -> last_question = "launch_urgencia"

  5. launch_urgencia
         -> Extrai urgencia -> TAG: urgencia_lancamento
         -> LAUNCH_ASK_CONTATO
         -> last_question = "launch_contato"

  6. launch_contato
         -> Extrai nome completo + email
         -> TAG: contato_completo_lancamento, email_lead
         -> Calcula score (launch_score):
              QUENTE (85-100) -> LAUNCH_QUENTE_AGENDAR, notif SLA 1h
              MORNO  (60-84)  -> LAUNCH_MORNO_MATERIAL, follow-up 24h
              FRIO   (0-59)   -> LAUNCH_MORNO_MATERIAL (mesma acao, follow-up 24h)
         -> awaiting_response = False
"""

import uuid
from datetime import timedelta

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.launch import (
    LAUNCH_ASK_CONTATO,
    LAUNCH_ASK_NOME,
    LAUNCH_ASK_PAGAMENTO,
    LAUNCH_ASK_PLANTA,
    LAUNCH_ASK_URGENCIA,
    LAUNCH_APRESENTAR,
    LAUNCH_CONHECE_NAO,
    LAUNCH_CONHECE_SIM,
    LAUNCH_MATERIAL_IMOVEL,
    LAUNCH_MORNO_MATERIAL,
    LAUNCH_QUENTE_AGENDAR,
)
from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question_async,
)
from src.agent.scoring.launch_score import calculate_launch_score
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.services.email_service import EmailService
from src.services.job_service import JobService
from src.services.kommo_service import KommoService
from src.services.lead_service import LeadService
from src.services.notification_service import NotificationService
from src.services.score_service import ScoreService
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

_CONHECE_REGIAO_PROMPT = (
    "O lead conhece ou demonstra familiaridade com a regiao mencionada?\n\n"
    "Categorias:\n"
    "- sim: O lead confirma que conhece ou ja visitou a regiao\n"
    "- nao: O lead nao conhece ou nao tem familiaridade com a regiao\n"
    "- off_topic: Resposta completamente fora do contexto (pergunta, assunto diferente, texto sem sentido)\n\n"
    "Considere qualquer confirmacao positiva como 'sim'.\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'sim', 'nao' ou 'off_topic'."
)

_PAGAMENTO_PROMPT = (
    "Classifique a forma de pagamento para lancamento imobiliario. "
    "Valor informado: {valor}\n\n"
    "Categorias validas:\n"
    "- a_vista: Pagamento a vista / sem financiamento\n"
    "- fgts: Usa FGTS como parte do pagamento\n"
    "- parcelas_direto: Parcelas direto na construtora\n"
    "- financiamento: Financiamento bancario\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_URGENCIA_PROMPT = (
    "Classifique o prazo/urgencia na categoria correta. "
    "Prazo informado: {valor}\n\n"
    "Categorias validas:\n"
    "- 30_dias: Ate 30 dias\n"
    "- 1_3_meses: Entre 1 e 3 meses\n"
    "- 3_6_meses: Entre 3 e 6 meses\n"
    "- sem_urgencia: Sem urgencia / sem prazo definido\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

# Dados do empreendimento de lancamento atual (Residencial Vista Park — LANC-DS-002)
# TODO Feature 17: buscar dinamicamente do catalogo/CRM conforme o imóvel referenciado
_EMPREENDIMENTO_PADRAO = "Residencial Vista Park"
_REGIAO_PADRAO = "Despraiado"
_ENTREGA_PADRAO = "junho/2026"
_SUITES_PADRAO = "4 suítes"
_DIFERENCIAIS_PADRAO = "Sala de Cinema, Adega Climatizada, Home Office e Lavabo"
_PONTOS_DESTAQUE_PADRAO = (
    "É uma das regiões mais tranquilas e valorizadas de Cuiabá, "
    "com ótima infraestrutura, fácil acesso pela Av. do CPA e "
    "próximo ao comércio e serviços do bairro"
)
_DISTANCIA_PADRAO = "10"
_PONTOS_REFERENCIA_PADRAO = "Shopping Três Américas e Av. Miguel Sutil"
_TIPOS_UNIDADE_PADRAO = "4 suítes"
_METRAGEM_MIN_PADRAO = "220"
_METRAGEM_MAX_PADRAO = "280"
_VAGAS_PADRAO = "2"
_PRECO_INICIAL_PADRAO = "1.200.000"
_LINK_FOTOS_PADRAO = ""   # TODO Feature 17: preencher com URL real
_LINK_TOUR_PADRAO = ""    # TODO Feature 17: preencher com URL real
_LINK_PLANTA_PADRAO = ""  # TODO Feature 17: preencher com URL real

_VAGUE_DATE_PROMPT = (
    "O lead informou um dia para a apresentacao/contato. "
    "A data e vaga (so dia da semana sem data especifica)?\n\n"
    "Se sim, qual dia da semana foi mencionado? "
    "Responda com o nome normalizado: "
    "'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo'.\n"
    "Se a data e completa (tem dia e mes, ex: 'dia 15', '15/04', 'proximo dia 10'), "
    "responda: 'especifico'.\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com o nome do dia ou 'especifico'."
)

_WEEKDAY_MAP: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}

_WEEKDAY_DISPLAY: dict[str, str] = {
    "segunda": "Segunda-feira",
    "terca": "Terça-feira",
    "quarta": "Quarta-feira",
    "quinta": "Quinta-feira",
    "sexta": "Sexta-feira",
    "sabado": "Sábado",
    "domingo": "Domingo",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ficha_material(tags: dict) -> str:
    """Monta a ficha do imóvel de lançamento para envio ao lead."""
    empreendimento = tags.get("lead_imovel_especifico") or _EMPREENDIMENTO_PADRAO
    regiao = tags.get("localizacao") or _REGIAO_PADRAO
    msg = LAUNCH_MATERIAL_IMOVEL.format(
        empreendimento=empreendimento,
        regiao=regiao,
        suites=_SUITES_PADRAO,
        metragem_min=_METRAGEM_MIN_PADRAO,
        metragem_max=_METRAGEM_MAX_PADRAO,
        vagas=_VAGAS_PADRAO,
        entrega=_ENTREGA_PADRAO,
        diferenciais=_DIFERENCIAIS_PADRAO,
        preco_inicial=_PRECO_INICIAL_PADRAO,
    )
    links = []
    if _LINK_FOTOS_PADRAO:
        links.append(f"📸 Fotos: {_LINK_FOTOS_PADRAO}")
    if _LINK_TOUR_PADRAO:
        links.append(f"🎥 Tour 360°: {_LINK_TOUR_PADRAO}")
    if _LINK_PLANTA_PADRAO:
        links.append(f"📐 Planta: {_LINK_PLANTA_PADRAO}")
    if links:
        msg += "\n\n" + "\n".join(links)
    return msg


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


async def _check_bool(prompt_template: str, message: str) -> bool:
    """Usa LLM para verificar uma condicao booleana na mensagem."""
    llm = _get_llm()
    prompt = prompt_template.format(message=message)
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


async def _confirm_launch_appointment(
    data: str,
    phone: str,
    lead_id: str | uuid.UUID | None,
    tags: dict,
    kommo,
    kommo_contact_id: str | None,
    kommo_lead_id: str | None,
) -> dict:
    """Salva tag, atualiza stage no Kommo e envia confirmação de apresentação."""
    if data and data not in ("nao informado", "nao_informado"):
        tags = await _save_tag(lead_id, tags, "apresentacao_agendada", "true")
        tags = await _save_tag(lead_id, tags, "data_apresentacao", data)
        logger.info(
            "LAUNCH | Apresentacao agendada: %r | TAG: apresentacao_agendada | phone=%s",
            data, phone,
        )
    else:
        tags = await _save_tag(lead_id, tags, "apresentacao_agendada", "true")

    await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
    if kommo_lead_id:
        stage_id = settings.kommo_stage_map_dict.get("oportunidade_quente")
        if stage_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

    msg_enc = (
        "Em breve nossa equipe entrará em contato para "
        "confirmar todos os detalhes. Até logo! 😊"
    )
    await send_whatsapp_message(phone, msg_enc)
    return {
        "current_node": "launch",
        "tags": tags,
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
        "awaiting_response": False,
        "last_question": "launch_encerrado",
        "messages": [AIMessage(content=msg_enc)],
    }


def _next_three_weekdays(weekday: int) -> tuple[str, str, str]:
    """Retorna as próximas três datas (dd/mm) de um dado dia da semana.

    Usa o fuso horário de Cuiabá/MT (UTC-4, sem horário de verão) para
    garantir que nunca exibimos o dia atual ou um dia já passado.
    """
    from datetime import datetime, timedelta, timezone

    cuiaba_tz = timezone(timedelta(hours=-4))
    today = datetime.now(tz=cuiaba_tz).date()

    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:  # 0 = hoje -> pula para a próxima ocorrência
        days_ahead += 7

    first = today + timedelta(days=days_ahead)
    second = first + timedelta(days=7)
    third = second + timedelta(days=7)
    return first.strftime("%d/%m"), second.strftime("%d/%m"), third.strftime("%d/%m")


# ---------------------------------------------------------------------------
# Node principal
# ---------------------------------------------------------------------------


async def launch_node(state: AgentState) -> dict:
    """
    Node: Fluxo de lancamento imobiliario com sistema de score (Feature 14).

    Consulte o docstring do modulo para detalhes de cada etapa.
    """
    phone = state["phone"]
    try:
        return await _launch_node_impl(state)
    except Exception as exc:
        logger.exception("LAUNCH | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("LAUNCH | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "launch"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _launch_node_impl(state: AgentState) -> dict:
    phone = state["phone"]
    lead_id = state.get("lead_id")
    lead_name = state.get("lead_name")
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

    # Extração proativa: captura qualquer informação útil mencionada pelo lead
    tags = await extract_context_from_message(effective_message, tags, lead_id)

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if await is_faq_question_async(effective_message):
        logger.info("LAUNCH | FAQ detectado em fluxo ativo | phone=%s", phone)
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
        logger.info("LAUNCH | Clarificacao detectada | lq=%s | phone=%s", last_question, phone)
        redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # -----------------------------------------------------------------------
    # Etapa 1: Capturar nome (resposta ao LAUNCH_ASK_NOME do buyer)
    # -----------------------------------------------------------------------
    if last_question is None:
        logger.info("LAUNCH | Capturando nome | phone=%s", phone)

        nome = await _extract_field(
            effective_message, "nome ou como o lead quer ser chamado"
        )
        nome_exibir = nome if nome != "nao informado" else (lead_name or "")

        tags = await _save_tag(
            lead_id, tags, "lead_lancamento_identificado", nome_exibir or "true"
        )
        tags = await _save_tag(
            lead_id, tags, "lead_identificado", nome_exibir or nome
        )

        logger.info(
            "LAUNCH | Nome capturado: %r | TAG lead_lancamento_identificado | phone=%s",
            nome_exibir,
            phone,
        )

        # Apresentar empreendimento (dados padrao - Feature 17 integrara com CRM)
        empreendimento = tags.get("lead_imovel_especifico") or _EMPREENDIMENTO_PADRAO
        regiao = tags.get("localizacao") or _REGIAO_PADRAO
        msg = LAUNCH_APRESENTAR.format(
            nome=nome_exibir or "voce",
            empreendimento=empreendimento,
            regiao=regiao,
            entrega=_ENTREGA_PADRAO,
            suites=_SUITES_PADRAO,
            diferenciais=_DIFERENCIAIS_PADRAO,
        )
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "launch",
            "tags": tags,
            "lead_name": nome_exibir or lead_name,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "launch_regiao",
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2: Verificar conhecimento da regiao + perguntar planta
    # -----------------------------------------------------------------------
    if last_question == "launch_regiao":
        logger.info("LAUNCH | Verificando conhecimento da regiao | phone=%s", phone)

        llm = _get_llm()
        regiao_resp = await llm.ainvoke(_CONHECE_REGIAO_PROMPT.format(message=effective_message))
        regiao_raw = regiao_resp.content.strip().lower()

        # Re-ask se resposta for completamente off-topic
        if "off_topic" in regiao_raw:
            if reask_count < 2:
                logger.info(
                    "LAUNCH | Resposta regiao off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "launch",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }

        conhece_regiao = regiao_raw.startswith("sim")
        regiao = tags.get("localizacao") or _REGIAO_PADRAO

        # Salvar tag de conhecimento da regiao (usada no score)
        tags = await _save_tag(
            lead_id, tags, "conhece_regiao_lancamento",
            "true" if conhece_regiao else "false"
        )

        if conhece_regiao:
            msg_regiao = LAUNCH_CONHECE_SIM
            logger.info("LAUNCH | Lead conhece a regiao | phone=%s", phone)
        else:
            msg_regiao = LAUNCH_CONHECE_NAO.format(
                regiao=regiao,
                pontos_destaque=_PONTOS_DESTAQUE_PADRAO,
                distancia=_DISTANCIA_PADRAO,
                pontos_referencia=_PONTOS_REFERENCIA_PADRAO,
            )
            logger.info("LAUNCH | Lead nao conhece a regiao | phone=%s", phone)

        # Envia info sobre a regiao + pergunta sobre planta no mesmo turno
        msg_planta = LAUNCH_ASK_PLANTA.format(
            tipos_unidade=_TIPOS_UNIDADE_PADRAO,
            metragem_min=_METRAGEM_MIN_PADRAO,
            metragem_max=_METRAGEM_MAX_PADRAO,
        )
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg_regiao)
        await send_whatsapp_message(phone, msg_planta)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "launch_planta",
            "messages": [
                AIMessage(content=msg_regiao),
                AIMessage(content=msg_planta),
            ],
        }

    # -----------------------------------------------------------------------
    # Etapa 3: Capturou tipo de unidade -> TAG: planta_interesse
    # -----------------------------------------------------------------------
    if last_question == "launch_planta":
        logger.info("LAUNCH | Capturando tipo de unidade | phone=%s", phone)

        planta = await _extract_field(
            effective_message,
            "tipo de unidade de interesse (studio, 1 suite, 2 suites, cobertura, etc)",
        )

        if _is_off_topic(planta):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "launch",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            planta = "nao informado"
        elif _is_missing(planta):
            planta = "nao informado"

        tags = await _save_tag(lead_id, tags, "planta_interesse", planta)

        logger.info(
            "LAUNCH | Planta=%r | TAG planta_interesse | phone=%s", planta, phone
        )

        nome_display = lead_name or tags.get("lead_identificado", "") or "voce"
        msg = LAUNCH_ASK_PAGAMENTO.format(nome=nome_display)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "launch_pagamento",
            "reask_count": 0,
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 4: Capturou forma de pagamento -> TAG: forma_pagamento_lancamento
    # -----------------------------------------------------------------------
    if last_question == "launch_pagamento":
        logger.info("LAUNCH | Capturando forma de pagamento | phone=%s", phone)

        pagamento = await _extract_field(
            effective_message,
            "forma de pagamento escolhida (a vista, FGTS, parcelas, financiamento)",
        )

        if _is_off_topic(pagamento):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "launch",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            pagamento = "nao informado"
        elif _is_missing(pagamento):
            pagamento = "nao informado"

        tags = await _save_tag(lead_id, tags, "forma_pagamento_lancamento", pagamento)

        logger.info(
            "LAUNCH | Pagamento=%r | TAG forma_pagamento_lancamento | phone=%s",
            pagamento,
            phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, LAUNCH_ASK_URGENCIA)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "launch_urgencia",
            "reask_count": 0,
            "messages": [AIMessage(content=LAUNCH_ASK_URGENCIA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 5: Capturou urgencia -> TAG: urgencia_lancamento
    # -----------------------------------------------------------------------
    if last_question == "launch_urgencia":
        logger.info("LAUNCH | Capturando urgencia | phone=%s", phone)

        urgencia = await _extract_field(
            effective_message, "prazo ou urgencia para fechar o negocio"
        )

        if _is_off_topic(urgencia):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "launch",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            urgencia = "nao informado"
        elif _is_missing(urgencia):
            urgencia = "nao informado"

        tags = await _save_tag(lead_id, tags, "urgencia_lancamento", urgencia)

        logger.info(
            "LAUNCH | Urgencia=%r | TAG urgencia_lancamento | phone=%s",
            urgencia,
            phone,
        )

        nome_display = lead_name or tags.get("lead_identificado", "") or "voce"
        msg_contato = LAUNCH_ASK_CONTATO.format(nome=nome_display)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg_contato)
        return {
            "current_node": "launch",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "launch_contato",
            "reask_count": 0,
            "messages": [AIMessage(content=msg_contato)],
        }

    # -----------------------------------------------------------------------
    # Etapa 6: Capturou contato completo -> calcular score -> agir
    # -----------------------------------------------------------------------
    if last_question == "launch_contato":
        logger.info(
            "LAUNCH | Capturando contato completo e calculando score | phone=%s",
            phone,
        )

        nome_completo = await _extract_field(
            effective_message, "nome completo do lead"
        )
        email = await _extract_field(effective_message, "endereco de e-mail")

        tem_email = email != "nao informado" and "@" in email
        tem_nome = nome_completo != "nao informado"

        if tem_email:
            tags = await _save_tag(lead_id, tags, "email_lead", email)
        if tem_nome:
            tags = await _save_tag(
                lead_id, tags, "contato_completo_lancamento", nome_completo
            )
            # Atualizar nome se melhor que o atual
            current_name = tags.get("lead_identificado", "")
            if not current_name or current_name in ("nao informado", "true"):
                tags = await _save_tag(
                    lead_id, tags, "lead_identificado", nome_completo
                )

        # Determinar nivel de contato para o score
        if tem_nome and tem_email:
            contato_nivel = "completo"
        elif tem_nome:
            contato_nivel = "whatsapp"
        elif tem_email:
            contato_nivel = "email"
        else:
            contato_nivel = "basico"

        # Classificar pagamento e urgencia para score
        pagamento_raw = tags.get("forma_pagamento_lancamento", "")
        urgencia_raw = tags.get("urgencia_lancamento", "")

        pagamento_categoria = await _classify_field(_PAGAMENTO_PROMPT, pagamento_raw)
        urgencia_categoria = await _classify_field(_URGENCIA_PROMPT, urgencia_raw)

        planta_informada = bool(
            tags.get("planta_interesse")
            and tags.get("planta_interesse") != "nao informado"
        )
        conhece_regiao = tags.get("conhece_regiao_lancamento") == "true"
        empreendimento_id = bool(tags.get("lead_imovel_especifico"))

        # Calcular score
        score_data = calculate_launch_score({
            "pagamento_categoria": pagamento_categoria,
            "urgencia_categoria": urgencia_categoria,
            "contato_nivel": contato_nivel,
            "planta_informada": planta_informada,
            "conhece_regiao": conhece_regiao,
            "empreendimento_id": empreendimento_id,
        })

        total_score = score_data["total_score"]
        classification = score_data["classification"]
        nome_display = (
            lead_name
            or tags.get("lead_lancamento_identificado")
            or tags.get("lead_identificado")
            or ""
        )
        # Remover "true" como nome
        if nome_display == "true":
            nome_display = ""

        logger.info(
            "LAUNCH | Score=%d | Classificacao=%s | "
            "pag=%s urg=%s contato=%s planta=%s regiao=%s | phone=%s",
            total_score,
            classification,
            pagamento_categoria,
            urgencia_categoria,
            contato_nivel,
            planta_informada,
            conhece_regiao,
            phone,
        )

        # Persistir score no banco
        # Mapeamento para ScoreService: contato_pts -> situacao_pts,
        # planta_pts + dados_pts -> dados_pts
        if lead_id:
            async with async_session() as session:
                score_svc = ScoreService(session)
                await score_svc.upsert(
                    lead_id=lead_id,
                    score_type="launch",
                    investimento_pts=0,
                    pagamento_pts=score_data["pagamento_pts"],
                    urgencia_pts=score_data["urgencia_pts"],
                    situacao_pts=score_data["contato_pts"],
                    dados_pts=score_data["planta_pts"] + score_data["dados_pts"],
                )

            # Atualizar classificacao do lead
            async with async_session() as session:
                lead_svc = LeadService(session)
                lead = await lead_svc.get_by_id(lead_id)
                if lead:
                    await lead_svc.update_classification(
                        lead, classification, total_score
                    )

        # Salvar classificação como tag para aparecer no CRM
        tags = await _save_tag(lead_id, tags, "classificacao_lancamento", classification)

        # Sincronizar tags com KOMMO e atualizar stage conforme classificacao
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        stage_id = kommo.stage_id_for_classification(classification)
        if stage_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        base_state = {
            "current_node": "launch",
            "tags": tags,
            "score_data": score_data,
            "total_score": total_score,
            "classification": classification,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

        # ----------------------------------------------------------------
        # Branch QUENTE (85-100 pts)
        # ----------------------------------------------------------------
        if classification == "quente":
            ficha_msg = _build_ficha_material(tags)
            await send_whatsapp_message(phone, ficha_msg)
            msg = LAUNCH_QUENTE_AGENDAR.format(nome=nome_display or "voce")
            await send_whatsapp_message(phone, msg)

            # Notificacao por email ao especialista de lancamento (SLA 1h)
            email_result = await EmailService().send_launch_specialist_notification(
                lead_name=nome_display,
                lead_phone=phone,
                lead_email=email if tem_email else tags.get("email_lead", ""),
                score=total_score,
                planta=tags.get("planta_interesse", ""),
                pagamento=tags.get("forma_pagamento_lancamento", ""),
                urgencia=tags.get("urgencia_lancamento", ""),
                empreendimento=tags.get("lead_imovel_especifico") or _EMPREENDIMENTO_PADRAO,
                origem=tags.get("origem_campanha") or tags.get("utm_source", ""),
            )
            logger.info(
                "LAUNCH | Email especialista | status=%s | phone=%s",
                email_result.get("status"),
                phone,
            )

            # Resumo do lead no KOMMO
            if kommo_lead_id:
                nota = (
                    f"🔴 LEAD LANÇAMENTO - URGENTE\n"
                    f"Score: {total_score} pontos\n"
                    f"Nome: {nome_display or 'Não informado'}\n"
                    f"Tel: {phone}\n"
                    f"Email: {(email if tem_email else tags.get('email_lead')) or 'Não informado'}\n"
                    f"Empreendimento: {tags.get('lead_imovel_especifico') or _EMPREENDIMENTO_PADRAO}\n"
                    f"Interesse: {tags.get('planta_interesse') or 'Não informado'}\n"
                    f"Pagamento: {tags.get('forma_pagamento_lancamento') or 'Não informado'}\n"
                    f"Urgência: {tags.get('urgencia_lancamento') or 'A definir'}\n"
                    f"Origem: {tags.get('origem_campanha') or tags.get('utm_source') or 'Direto'}"
                )
                await kommo.add_note_to_lead(kommo_lead_id, nota)

            # Notificacao corretor URGENTE (SLA 1h)
            if lead_id:
                async with async_session() as session:
                    notif_svc = NotificationService(session)
                    await notif_svc.create(
                        lead_id=lead_id,
                        notification_type="corretor_urgente",
                        sla_hours=1,
                        payload={
                            "phone": phone,
                            "score": total_score,
                            "nome": nome_display,
                            "email": email if tem_email else "",
                            "planta": tags.get("planta_interesse", ""),
                            "pagamento": tags.get("forma_pagamento_lancamento", ""),
                            "urgencia": tags.get("urgencia_lancamento", ""),
                            "tipo": "lancamento_quente",
                        },
                    )
                logger.info(
                    "LAUNCH | Notificacao URGENTE (SLA 1h) criada "
                    "| phone=%s | score=%d",
                    phone,
                    total_score,
                )

            return {
                **base_state,
                "awaiting_response": True,
                "last_question": "launch_quente_data",
                "reask_count": 0,
                "messages": [AIMessage(content=ficha_msg), AIMessage(content=msg)],
            }

        # ----------------------------------------------------------------
        # Branch MORNO ou FRIO (< 85 pts) -> enviar material + follow-up
        # ----------------------------------------------------------------
        msg = LAUNCH_MORNO_MATERIAL.format(nome=nome_display or "voce")
        await send_whatsapp_message(phone, msg)
        ficha_msg = _build_ficha_material(tags)
        await send_whatsapp_message(phone, ficha_msg)

        if lead_id:
            # Agendar follow-up 24h
            async with async_session() as session:
                job_svc = JobService(session)
                await job_svc.schedule_after(
                    lead_id=lead_id,
                    job_type="follow_up_24h",
                    delay=timedelta(hours=24),
                    payload={
                        "phone": phone,
                        "score": total_score,
                        "tipo": "lancamento_morno",
                    },
                )

            # Notificacao corretor PADRAO (SLA 24h)
            async with async_session() as session:
                notif_svc = NotificationService(session)
                await notif_svc.create(
                    lead_id=lead_id,
                    notification_type="corretor_padrao",
                    sla_hours=24,
                    payload={
                        "phone": phone,
                        "score": total_score,
                        "nome": nome_display,
                        "planta": tags.get("planta_interesse", ""),
                        "pagamento": tags.get("forma_pagamento_lancamento", ""),
                        "tipo": "lancamento_morno",
                    },
                )
            logger.info(
                "LAUNCH | MORNO: material enviado + follow-up 24h agendado "
                "| phone=%s | score=%d",
                phone,
                total_score,
            )

        return {
            **base_state,
            "awaiting_response": False,
            "last_question": "launch_encerrado",
            "messages": [AIMessage(content=msg), AIMessage(content=ficha_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa: Lead quente respondeu data/horario da apresentacao
    # -----------------------------------------------------------------------
    if last_question == "launch_quente_data":
        logger.info("LAUNCH | Capturando data da apresentacao | phone=%s", phone)

        # Verificar se o lead informou apenas dia da semana (sem data especifica)
        llm = _get_llm()
        vague_resp = await llm.ainvoke(_VAGUE_DATE_PROMPT.format(message=effective_message))
        vague_day = vague_resp.content.strip().lower().rstrip(".")

        if vague_day in _WEEKDAY_MAP:
            weekday_num = _WEEKDAY_MAP[vague_day]
            d1, d2, d3 = _next_three_weekdays(weekday_num)
            day_label = _WEEKDAY_DISPLAY.get(vague_day, vague_day.capitalize())
            msg = (
                f"Que ótimo! Qual das próximas {day_label}s fica melhor para você?\n\n"
                f"• {day_label} {d1}\n"
                f"• {day_label} {d2}\n"
                f"• {day_label} {d3}"
            )
            logger.info(
                "LAUNCH | Data vaga (%s) -> perguntando qual das 3 proximas | phone=%s",
                vague_day, phone,
            )
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "launch",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "launch_quente_data_confirm",
                "messages": [AIMessage(content=msg)],
            }

        # Data especifica informada -> confirmar e encerrar
        data_apresentacao = await _extract_field(
            effective_message, "data e horario da apresentacao informados pelo lead"
        )
        return await _confirm_launch_appointment(
            data_apresentacao, phone, lead_id, tags, kommo,
            kommo_contact_id, kommo_lead_id,
        )

    # -----------------------------------------------------------------------
    # Etapa: Lead confirmou a data especifica da apresentacao (apos clarificacao)
    # -----------------------------------------------------------------------
    if last_question == "launch_quente_data_confirm":
        logger.info("LAUNCH | Confirmando data especifica da apresentacao | phone=%s", phone)

        data_apresentacao = await _extract_field(
            effective_message, "data e horario da apresentacao informados pelo lead"
        )
        return await _confirm_launch_appointment(
            data_apresentacao, phone, lead_id, tags, kommo,
            kommo_contact_id, kommo_lead_id,
        )

    # -----------------------------------------------------------------------
    # Fallback: estado desconhecido - NAO reiniciar, rotear para completed
    # -----------------------------------------------------------------------
    logger.warning(
        "LAUNCH | Estado desconhecido last_question=%r - roteando p/ completed | phone=%s",
        last_question,
        phone,
    )
    return {
        "current_node": "completed",
        "tags": tags,
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
        "awaiting_response": False,
        "last_question": last_question,
        "is_silenced": False,
    }
