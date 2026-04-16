"""
buyer.py - Node do fluxo de comprador (Feature 14).

Qualifica o ticket do comprador e encaminha para o sub-fluxo correto
(lancamento ou imovel pronto). Este node e sempre acionado apos o
node specific, que configura current_node = "buyer".

A deteccao de "primeira chamada" usa last_question is None
(em vez de current_node != "buyer"), pois este node e ativado
pelo proprio current_node = "buyer" definido pelo specific_node.

Etapas (rastreadas por last_question):
  1. last_question is None (vindo do specific, que enviou BUYER_ASK_TIPO)
         -> A mensagem atual e a resposta ao BUYER_ASK_TIPO (lancamento ou pronto?)
         -> Classificar tipo: lancamento | pronto | indefinido
         -> Indefinido: re-perguntar (ate 2 tentativas)
         -> Salva tipo em tag situacao_imovel
         -> BUYER_ASK_TICKET -> last_question = "buyer_tipo"

  2. buyer_tipo
         -> A mensagem atual e a resposta ao BUYER_ASK_TICKET (orcamento/faixa)
         -> Verificar se abaixo ou acima de R$400K
         -> Abaixo: TAG: lead_fora_perfil, mensagem fora perfil, encerra
         -> Acima + tipo=pronto: TAG: situacao_imovel=pronto
                                 PRONTO_ASK_NOME -> last_question = "buyer_pronto_nome"
         -> Acima + tipo=lancamento: envia LAUNCH_ASK_NOME, current_node = "launch",
                                     last_question = None (transiciona para launch_node)

  3. buyer_pronto_nome
         -> Extrai nome -> TAG: lead_imovel_especifico, lead_identificado
         -> PRONTO_ASK_FAIXA_VALOR -> last_question = "buyer_pronto_faixa"

  4. buyer_pronto_faixa
         -> Extrai faixa de investimento -> TAG: faixa_valor
         -> PRONTO_ASK_FORMA_PAGAMENTO -> last_question = "buyer_pronto_pagamento"

  5. buyer_pronto_pagamento
         -> Extrai forma de pagamento -> TAG: forma_pagamento
         -> PRONTO_ASK_URGENCIA -> last_question = "buyer_pronto_urgencia"

  6. buyer_pronto_urgencia
         -> Extrai urgencia/prazo -> TAG: urgencia
         -> PRONTO_ASK_PRIORIDADES -> last_question = "buyer_pronto_prioridades"

  7. buyer_pronto_prioridades
         -> Extrai prioridades -> TAG: prioridades
         -> Classifica categorias (investimento, pagamento, urgencia, situacao)
         -> Calcula score (0-100 pts) e persiste no banco
         -> QUENTE (85-100): PRONTO_APRESENTAR + notif corretor urgente (SLA 2h)
                             last_question = "buyer_pronto_preferencias"
         -> MORNO  (60-84):  PRONTO_APRESENTAR + notif corretor padrao (SLA 24h)
                             last_question = "buyer_pronto_preferencias"
         -> FRIO   (0-59):   PRONTO_ASK_BARREIRA -> last_question = "buyer_pronto_barreira"

  8. buyer_pronto_preferencias
         -> Extrai regiao e suites
         -> PRONTO_APRESENTAR_DETALHES -> last_question = "buyer_pronto_visita"

  9. buyer_pronto_visita
         -> Quer visitar?
         -> Sim: PRONTO_AGENDAR_VISITA -> last_question = "buyer_pronto_data"
         -> Nao: PRONTO_ASK_BARREIRA -> last_question = "buyer_pronto_barreira"

  10. buyer_pronto_data
         -> Extrai data/horario -> TAG: visita_agendada
         -> Notifica corretor (SLA 2h)
         -> PRONTO_VISITA_CONFIRMADA -> awaiting_response = False

  11. buyer_pronto_barreira (Secao 3.5 PDF — Identificar Barreira)
         -> LLM classifica barreira: financeira | timing | conhecimento
         -> financeira: TAG: consultoria_agendada, notif corretor_padrao (24h)
                        PRONTO_BARREIRA_FINANCEIRA
         -> timing: TAG: lista_vip, agenda nurture_30d
                    PRONTO_BARREIRA_TIMING
         -> conhecimento: TAG: tour_agendado, notif corretor_padrao (24h)
                          PRONTO_BARREIRA_CONHECIMENTO -> awaiting_response = True
"""

import re
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
from src.agent.prompts.launch import (
    BUYER_ASK_PREFERENCIAS,
    BUYER_ASK_TICKET,
    BUYER_ASK_TIPO,
    BUYER_FORA_PERFIL,
    BUYER_FORA_PERFIL_CONTATO,
    LAUNCH_ASK_NOME,
    PRONTO_AGENDAR_VISITA,
    PRONTO_APRESENTAR,
    PRONTO_APRESENTAR_DETALHES,
    PRONTO_ASK_BARREIRA,
    PRONTO_ASK_FORMA_PAGAMENTO,
    PRONTO_ASK_NOME,
    PRONTO_ASK_PRIORIDADES,
    PRONTO_ASK_URGENCIA,
    PRONTO_BARREIRA_CONHECIMENTO,
    PRONTO_BARREIRA_FINANCEIRA,
    PRONTO_BARREIRA_TIMING,
    PRONTO_VISITA_CONFIRMADA,
)
from src.agent.scoring.investor_score import calculate_investor_score
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.db.database import async_session
from src.properties.catalog import search_properties
from src.properties.formatter import format_property_whatsapp
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

_TICKET_PROMPT = (
    "O lead esta buscando imovel com faixa de preco abaixo de R$ 400.000 "
    "(quatrocentos mil reais)? Considere qualquer mencao de valor, "
    "orcamento, budget ou preco.\n\n"
    "Se o lead mencionou um valor inferior a R$ 400.000, responda 'sim'.\n"
    "Se o valor for R$ 400.000 ou superior, ou se nao mencionou valor, responda 'nao'.\n\n"
    "Responda apenas 'sim' (abaixo de 400K) ou 'nao' (acima ou nao informado).\n\n"
    "Mensagem: {message}"
)

_TIPO_IMOVEL_PROMPT = (
    "O lead prefere lancamento imobiliario (imovel na planta, em construcao) "
    "ou imovel pronto para morar?\n\n"
    "Categorias:\n"
    "- lancamento: Menciona lancamento, na planta, em construcao, construtora, etc\n"
    "- pronto: Menciona imovel pronto, entrega imediata, ja acabado, etc\n"
    "- indefinido: Resposta ambigua, irrelevante ou sem mencao clara ao tipo de imovel\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'lancamento', 'pronto' ou 'indefinido'."
)

_QUER_VISITA_PROMPT = (
    "O lead esta aceitando ou confirmando que quer visitar/conhecer o imovel?\n\n"
    "Categorias:\n"
    "- sim: O lead confirma que quer visitar ou conhecer o imovel\n"
    "- nao: O lead recusa ou diz que nao quer visitar agora\n"
    "- off_topic: Resposta completamente fora do contexto (pergunta, assunto diferente, texto sem sentido)\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com 'sim', 'nao' ou 'off_topic'."
)

_BARREIRA_PROMPT = (
    "O lead explicou por que nao quer agendar uma visita agora. "
    "Classifique a barreira principal:\n\n"
    "- financeira: Questao de orcamento, financiamento, credito, dinheiro, preco\n"
    "- timing: Ainda nao e o momento, vai pensar, sem urgencia, nao e agora\n"
    "- conhecimento: Quer conhecer mais opcoes, pesquisar mais, ver mais imoveis\n"
    "- off_topic: Resposta completamente fora do contexto, sem relacao com barreira alguma\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com: 'financeira', 'timing', 'conhecimento' ou 'off_topic'."
)

_CLASSIFY_INVESTIMENTO_PROMPT = (
    "Classifique a faixa de investimento na categoria correta. "
    "Valor informado: {valor}\n\n"
    "Categorias validas:\n"
    "- acima_2m: Acima de R$2.000.000\n"
    "- 1m_2m: Entre R$1.000.000 e R$2.000.000\n"
    "- 500k_1m: Entre R$500.000 e R$1.000.000\n"
    "- 400k_500k: Entre R$400.000 e R$500.000\n"
    "- abaixo_400k: Abaixo de R$400.000\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_CLASSIFY_PAGAMENTO_PROMPT = (
    "Classifique a forma de pagamento na categoria correta. "
    "Forma informada: {valor}\n\n"
    "Categorias validas:\n"
    "- a_vista: Pagamento a vista / sem financiamento\n"
    "- permuta: Permuta de imovel\n"
    "- financiamento_aprovado: Financiamento ja aprovado no banco\n"
    "- vai_financiar: Pretende financiar (ainda nao aprovado)\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_CLASSIFY_URGENCIA_PROMPT = (
    "Classifique o prazo/urgencia na categoria correta. "
    "Prazo informado: {valor}\n\n"
    "Categorias validas:\n"
    "- 30_dias: Ate 30 dias\n"
    "- 1_3_meses: Entre 1 e 3 meses\n"
    "- 3_6_meses: Entre 3 e 6 meses\n"
    "- sem_urgencia: Sem urgencia / sem prazo definido / nao sabe\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "ATENCAO: Se o valor for uma forma de pagamento (ex: 'a vista', 'financiamento', "
    "'FGTS', 'permuta') SEM mencao a prazo de tempo, classifique como 'nao_informado'.\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_CLASSIFY_SITUACAO_PROMPT = (
    "Classifique a preferencia de situacao do imovel na categoria correta. "
    "Situacao informada: {valor}\n\n"
    "Categorias validas:\n"
    "- pronto: Prefere imovel pronto para morar\n"
    "- lancamento: Aceita ou prefere lancamento\n"
    "- tanto_faz: Tanto faz / qualquer situacao\n"
    "- nao_informado: Nao foi possivel identificar\n\n"
    "Responda APENAS com a categoria, sem explicacoes."
)

_VAGUE_DATE_PROMPT = (
    "O lead informou um dia para a visita/contato. "
    "A data e vaga (so dia da semana sem data especifica)?\n\n"
    "Se sim, qual dia da semana foi mencionado? "
    "Responda com o nome normalizado: "
    "'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo'.\n"
    "Se a data e completa (tem dia e mes, ex: 'dia 15', '15/04', 'proximo dia 10'), "
    "responda: 'especifico'.\n\n"
    "Mensagem: {message}\n\n"
    "Responda APENAS com o nome do dia ou 'especifico'."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


async def _check_bool(prompt_template: str, message: str) -> bool:
    """Usa LLM para verificar uma condicao booleana na mensagem."""
    llm = _get_llm()
    prompt = prompt_template.format(message=message)
    response = await llm.ainvoke(prompt)
    return response.content.strip().lower().startswith("sim")


async def _classify_field(prompt_template: str, valor: str) -> str:
    """Usa LLM para classificar um valor em uma categoria pre-definida."""
    llm = _get_llm()
    prompt = prompt_template.format(valor=valor)
    response = await llm.ainvoke(prompt)
    return response.content.strip().lower()


# ---------------------------------------------------------------------------
# Qualificacao pronto: sequencia global de etapas (data-driven)
# ---------------------------------------------------------------------------

def _tag_collected(tags: dict, key: str) -> bool:
    """Retorna True se o campo já foi coletado com valor válido."""
    val = tags.get(key)
    return bool(val) and str(val).lower() not in ("nao informado", "nao_informado", "")


# Sequência de coleta do fluxo pronto.
# Cada entrada: (tag_key, last_question_id, prompt_a_enviar)
# _advance_pronto_qualification percorre esta lista e pula automaticamente
# qualquer etapa cujo dado já esteja nas tags do lead.
_PRONTO_QUALIFICATION_STEPS: list[tuple[str, str, str]] = [
    ("lead_identificado",  "buyer_pronto_nome",        PRONTO_ASK_NOME),
    ("forma_pagamento",    "buyer_pronto_pagamento",    PRONTO_ASK_FORMA_PAGAMENTO),
    ("urgencia",           "buyer_pronto_urgencia",     PRONTO_ASK_URGENCIA),
    ("prioridades",        "buyer_pronto_prioridades",  PRONTO_ASK_PRIORIDADES),
]


async def _advance_pronto_qualification(
    phone: str,
    tags: dict,
    after_step: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Envia a próxima pergunta de qualificação cujo dado ainda não foi coletado.

    Se after_step for fornecido, começa a busca a partir do passo SEGUINTE a ele.
    Retorna (last_question, mensagem) do passo enviado, ou (None, None) se todos
    os campos já estiverem coletados.
    """
    start = 0
    if after_step is not None:
        for i, (_, lq, _) in enumerate(_PRONTO_QUALIFICATION_STEPS):
            if lq == after_step:
                start = i + 1
                break

    for tag_key, last_q, msg in _PRONTO_QUALIFICATION_STEPS[start:]:
        if not _tag_collected(tags, tag_key):
            await send_whatsapp_message(phone, msg)
            return last_q, msg

    return None, None  # todos os campos já coletados


def _count_dados_preenchidos(tags: dict) -> int:
    """Conta quantos campos chave foram preenchidos para o score de dados."""
    campos = [
        "lead_tipo_imovel",
        "lead_identificado",
        "localizacao",
        "faixa_valor",
        "necessidades",
        "vagas_garagem",
        "situacao_imovel",
        "forma_pagamento",
        "urgencia",
        "prioridades",
    ]
    return sum(
        1
        for campo in campos
        if tags.get(campo) and tags[campo] != "nao informado"
    )


async def _save_tag(lead_id: str | uuid.UUID | None, tags: dict, key: str, value: str) -> dict:
    """Persiste tag no banco e retorna o dict de tags atualizado."""
    tags_update = dict(tags)
    tags_update[key] = value
    if lead_id:
        async with async_session() as session:
            tag_svc = TagService(session)
            await tag_svc.set_tag(lead_id, key, value)
    return tags_update


# Detecta se a string de data já contém informação de horário
_TIME_INFO_RE = re.compile(
    r"\b\d{1,2}h\b|\b\d{1,2}:\d{2}\b|manh[ãa]|tarde|noite|\bàs?\s+\d{1,2}\b",
    re.IGNORECASE,
)


def _has_time_info(text: str) -> bool:
    """Retorna True se o texto contém horário ou período do dia."""
    return bool(_TIME_INFO_RE.search(text or ""))


async def _finalize_visit_scheduling(
    phone: str,
    lead_id,
    lead_name: str | None,
    tags: dict,
    kommo: "KommoService",
    kommo_lead_id,
    kommo_contact_id,
    data_horario: str,
) -> dict:
    """Registra visita, cria notificação/job e confirma ao lead."""
    nome_display = lead_name or tags.get("lead_identificado", "")
    tags = await _save_tag(lead_id, tags, "visita_agendada", "true")
    tags = await _save_tag(lead_id, tags, "data_visita", data_horario)

    logger.info(
        "BUYER | Visita agendada: %r | TAG: visita_agendada | phone=%s",
        data_horario, phone,
    )

    if lead_id:
        async with async_session() as session:
            notif_svc = NotificationService(session)
            await notif_svc.create(
                lead_id=lead_id,
                notification_type="corretor_urgente",
                sla_hours=2,
                payload={
                    "phone": phone,
                    "nome": nome_display,
                    "regiao": tags.get("localizacao", ""),
                    "suites": tags.get("suites_interesse", ""),
                    "faixa_valor": tags.get("faixa_valor", ""),
                    "forma_pagamento": tags.get("forma_pagamento", ""),
                    "urgencia": tags.get("urgencia", ""),
                    "data_visita": data_horario,
                    "tipo": "imovel_pronto",
                },
            )
        logger.info(
            "BUYER | Notificacao corretor URGENTE (SLA 2h) criada | phone=%s", phone
        )

        async with async_session() as session:
            job_svc = JobService(session)
            await job_svc.schedule_after(
                lead_id,
                "reminder_24h_before",
                timedelta(hours=24),
                payload={
                    "name": nome_display or "voce",
                    "visit_time": data_horario,
                    "property_address": tags.get("localizacao", ""),
                },
            )
        logger.info("BUYER | Job reminder_24h_before agendado | lead_id=%s", lead_id)

    msg = PRONTO_VISITA_CONFIRMADA.format(nome=nome_display or "voce")
    await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
    if kommo_lead_id:
        stage_id = settings.kommo_stage_map_dict.get("oportunidade_quente")
        if stage_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)
    await send_whatsapp_message(phone, msg)
    return {
        "current_node": "buyer",
        "tags": tags,
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
        "awaiting_response": False,
        "last_question": "buyer_encerrado",
        "messages": [AIMessage(content=msg)],
    }


# ---------------------------------------------------------------------------
# Node principal
# ---------------------------------------------------------------------------


async def buyer_node(state: AgentState) -> dict:
    """
    Node: Fluxo de comprador com qualificacao completa (Feature 14).

    Consulte o docstring do modulo para detalhes de cada etapa.
    """
    phone = state["phone"]
    try:
        return await _buyer_node_impl(state)
    except Exception as exc:
        logger.exception("BUYER | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("BUYER | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "buyer"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _buyer_node_impl(state: AgentState) -> dict:
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

    # -----------------------------------------------------------------------
    # FAQ global: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    # -----------------------------------------------------------------------
    if await is_faq_question_async(effective_message):
        logger.info("BUYER | FAQ detectado em fluxo ativo | phone=%s", phone)
        return {
            "current_node": "faq",
            "last_question": last_question if last_question else "buyer_tipo_ask",
            "awaiting_response": True,
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
        }

    # -----------------------------------------------------------------------
    # Clarificação global: lead pediu esclarecimento da pergunta atual
    # -----------------------------------------------------------------------
    if is_clarification(effective_message):
        # last_question com valor: re-explica a pergunta específica
        # last_question is None: lead está respondendo ao BUYER_ASK_TIPO
        lq_label = last_question if last_question else "buyer_tipo_ask"
        logger.info("BUYER | Clarificacao detectada | lq=%s | phone=%s", lq_label, phone)
        redirect_msg = await build_smart_redirect(effective_message, lq_label, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # -----------------------------------------------------------------------
    # Etapa 1: Determinar lancamento ou imovel pronto (resposta ao BUYER_ASK_TIPO do specific)
    # -----------------------------------------------------------------------
    if last_question is None or last_question == "buyer_tipo_ask":
        logger.info("BUYER | Classificando tipo de imovel (lancamento/pronto) | phone=%s", phone)

        llm = _get_llm()
        tipo_resp = await llm.ainvoke(
            _TIPO_IMOVEL_PROMPT.format(message=effective_message)
        )
        tipo = tipo_resp.content.strip().lower()

        # Tipo indefinido: verificar se o lead forneceu budget em vez de tipo
        if tipo not in ("lancamento", "pronto"):
            faixa_capturada = _tag_collected(tags, "faixa_valor")
            if faixa_capturada:
                # Lead deu budget → verificar se abaixo ou acima de R$400K
                abaixo_400k = await _check_bool(_TICKET_PROMPT, effective_message)
                if abaixo_400k:
                    nome_display = lead_name or tags.get("lead_identificado", "")
                    tags = await _save_tag(lead_id, tags, "lead_fora_perfil", "true")
                    nome_prefix = f"{nome_display}, " if nome_display else ""
                    msg = BUYER_FORA_PERFIL.format(nome=nome_prefix)
                    await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
                    await send_whatsapp_message(phone, msg)
                    logger.info(
                        "BUYER | Fora perfil detectado via budget na Etapa 1 | phone=%s", phone
                    )
                    return {
                        "current_node": "buyer",
                        "tags": tags,
                        "kommo_contact_id": kommo_contact_id,
                        "kommo_lead_id": kommo_lead_id,
                        "awaiting_response": True,
                        "last_question": "buyer_fora_perfil_resp",
                        "messages": [AIMessage(content=msg)],
                    }
                # Budget ≥ 400k e tipo indefinido → perguntar preferências
                tags = await _save_tag(lead_id, tags, "situacao_imovel", "pronto")
                await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
                logger.info(
                    "BUYER | Budget >=400k capturado, tipo indefinido -> preferencias | phone=%s",
                    phone,
                )
                await send_whatsapp_message(phone, BUYER_ASK_PREFERENCIAS)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "awaiting_response": True,
                    "last_question": "buyer_pronto_estilo",
                    "reask_count": 0,
                    "messages": [AIMessage(content=BUYER_ASK_PREFERENCIAS)],
                }

            # Sem budget capturado → re-ask tipo (1 tentativa)
            if reask_count < 1:
                logger.info(
                    "BUYER | Tipo indefinido (%r) -> re-perguntando | reask=%d | phone=%s",
                    tipo, reask_count, phone,
                )
                redirect_msg = (
                    "Qual é a sua preferência:\n\n"
                    "• *Imóvel pronto para morar* — disponível imediatamente\n"
                    "• *Lançamento* — imóvel na planta ou em construção, com condições especiais de pagamento"
                )
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "awaiting_response": True,
                    "last_question": None,
                    "reask_count": reask_count + 1,
                }
            # Apos 1 tentativa sem resposta clara: usa o que o extrator captou ou "pronto"
            tipo = tags.get("situacao_imovel") or "pronto"
            logger.info(
                "BUYER | Tipo ainda indefinido -> fallback: %r | phone=%s", tipo, phone,
            )

        # Salva tipo em tag para roteamento na Etapa 2
        tags = await _save_tag(lead_id, tags, "situacao_imovel", tipo)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        logger.info("BUYER | Tipo=%r -> perguntando ticket | phone=%s", tipo, phone)
        await send_whatsapp_message(phone, BUYER_ASK_TICKET)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "buyer_tipo",
            "reask_count": 0,
            "messages": [AIMessage(content=BUYER_ASK_TICKET)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2: Verificar ticket (resposta ao BUYER_ASK_TICKET) e rotear
    # -----------------------------------------------------------------------
    if last_question == "buyer_tipo":
        logger.info("BUYER | Verificando ticket do lead | phone=%s", phone)

        abaixo_400k = await _check_bool(_TICKET_PROMPT, effective_message)

        # Extrair e salvar faixa_valor da resposta ao BUYER_ASK_TICKET
        faixa_extract = await _extract_field(
            effective_message, "faixa de investimento ou orcamento para o imovel"
        )
        if not _is_off_topic(faixa_extract) and not _is_missing(faixa_extract):
            tags = await _save_tag(lead_id, tags, "faixa_valor", faixa_extract)
            logger.info(
                "BUYER | Faixa_valor extraida na Etapa 2: %r | phone=%s", faixa_extract, phone
            )

        if abaixo_400k:
            nome_display = lead_name or tags.get("lead_identificado", "")
            tags = await _save_tag(lead_id, tags, "lead_fora_perfil", "true")

            nome_prefix = f"{nome_display}, " if nome_display else ""
            msg = BUYER_FORA_PERFIL.format(nome=nome_prefix)
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, msg)

            logger.info(
                "BUYER | Lead fora do perfil (abaixo R$400K) "
                "| TAG: lead_fora_perfil | phone=%s",
                phone,
            )
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_fora_perfil_resp",
                "messages": [AIMessage(content=msg)],
            }

        # Acima de R$400K -> rotear baseado no tipo salvo na Etapa 1
        tipo_salvo = tags.get("situacao_imovel") or "lancamento"
        logger.info("BUYER | Tipo salvo para roteamento: %r | phone=%s", tipo_salvo, phone)

        if tipo_salvo == "pronto":
            logger.info(
                "BUYER | Ticket ok + tipo=pronto -> iniciando fluxo pronto | phone=%s", phone
            )
            # Sincronizar nome do lead nas tags para permitir skip automático
            if lead_name and not _tag_collected(tags, "lead_identificado"):
                tags = await _save_tag(lead_id, tags, "lead_identificado", lead_name)
            if not tags.get("lead_imovel_especifico"):
                tags = await _save_tag(lead_id, tags, "lead_imovel_especifico", "true")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

            next_q, next_msg = await _advance_pronto_qualification(phone, tags)
            if next_q is None:
                # Todos os dados já coletados → ir direto ao cálculo de score
                next_q = "buyer_pronto_prioridades"
                next_msg = PRONTO_ASK_PRIORIDADES
                await send_whatsapp_message(phone, next_msg)
                logger.info("BUYER | Todos os dados já coletados -> score direto | phone=%s", phone)

            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": next_q,
                "reask_count": 0,
                "messages": [AIMessage(content=next_msg)],
            }

        # Lancamento -> verificar se é interesse específico (empreendimento conhecido) ou geral
        imovel_especifico = tags.get("lead_imovel_especifico")
        interesse_especifico = bool(
            imovel_especifico and imovel_especifico not in ("true", "nao informado")
        )

        if interesse_especifico:
            # Veio de anúncio específico → transicionar para launch_node com o empreendimento
            logger.info(
                "BUYER | Ticket ok + lancamento específico (%r) -> launch_node | phone=%s",
                imovel_especifico,
                phone,
            )
            msg = LAUNCH_ASK_NOME.format(empreendimento=imovel_especifico)
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "launch",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": None,
                "messages": [AIMessage(content=msg)],
            }

        # Lançamento geral → qualificar preferências sem apresentar empreendimento específico
        logger.info(
            "BUYER | Ticket ok + lancamento geral -> qualificar preferências | phone=%s",
            phone,
        )
        await send_whatsapp_message(phone, BUYER_ASK_PREFERENCIAS)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "buyer_pronto_estilo",
            "reask_count": 0,
            "messages": [AIMessage(content=BUYER_ASK_PREFERENCIAS)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2b: Captura estilo/preferencias (bypass de budget antes do tipo)
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_estilo":
        logger.info("BUYER | Capturando estilo/preferencias | phone=%s", phone)

        estilo = await _extract_field(
            effective_message,
            "estilo ou tipo de imóvel de interesse (apartamento, casa, cobertura, condominio, etc)",
        )
        if not _is_off_topic(estilo) and not _is_missing(estilo):
            tags = await _save_tag(lead_id, tags, "estilo_imovel", estilo)
            logger.info("BUYER | Estilo=%r | TAG estilo_imovel | phone=%s", estilo, phone)

        if lead_name and not _tag_collected(tags, "lead_identificado"):
            tags = await _save_tag(lead_id, tags, "lead_identificado", lead_name)
        if not tags.get("lead_imovel_especifico"):
            tags = await _save_tag(lead_id, tags, "lead_imovel_especifico", "true")

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        next_q, next_msg = await _advance_pronto_qualification(phone, tags)
        if next_q is None:
            next_q = "buyer_pronto_prioridades"
            next_msg = PRONTO_ASK_PRIORIDADES
            await send_whatsapp_message(phone, next_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": next_q,
            "reask_count": 0,
            "messages": [AIMessage(content=next_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 3: Imovel pronto - coletar nome
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_nome":
        logger.info("BUYER | Coletando nome (imovel pronto) | phone=%s", phone)

        nome = await _extract_field(
            effective_message, "nome ou como o lead quer ser chamado"
        )

        if _is_off_topic(nome):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            nome = "nao informado"
        elif _is_missing(nome):
            nome = "nao informado"

        nome_exibir = nome if nome != "nao informado" else (lead_name or "")

        if not tags.get("lead_imovel_especifico"):
            tags = await _save_tag(lead_id, tags, "lead_imovel_especifico", "true")
        tags = await _save_tag(
            lead_id, tags, "lead_identificado", nome_exibir or nome
        )

        logger.info(
            "BUYER | Nome capturado: %r | TAG: lead_imovel_especifico, lead_identificado | phone=%s",
            nome_exibir,
            phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        next_q, next_msg = await _advance_pronto_qualification(
            phone, tags, after_step="buyer_pronto_nome"
        )
        if next_q is None:
            next_q = "buyer_pronto_prioridades"
            next_msg = PRONTO_ASK_PRIORIDADES
            await send_whatsapp_message(phone, next_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "lead_name": nome_exibir or lead_name,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": next_q,
            "reask_count": 0,
            "messages": [AIMessage(content=next_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 4: Imovel pronto - coletar faixa de valor
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_faixa":
        logger.info("BUYER | Coletando faixa de valor | phone=%s", phone)

        faixa = await _extract_field(
            effective_message, "faixa de investimento ou orcamento para o imovel"
        )

        if _is_off_topic(faixa):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            faixa = "nao informado"
        elif _is_missing(faixa):
            faixa = "nao informado"

        tags = await _save_tag(lead_id, tags, "faixa_valor", faixa)

        logger.info(
            "BUYER | Faixa=%r | TAG: faixa_valor | phone=%s", faixa, phone
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        # after_step="buyer_pronto_nome" porque faixa fica entre nome e pagamento
        next_q, next_msg = await _advance_pronto_qualification(
            phone, tags, after_step="buyer_pronto_nome"
        )
        if next_q is None:
            next_q = "buyer_pronto_prioridades"
            next_msg = PRONTO_ASK_PRIORIDADES
            await send_whatsapp_message(phone, next_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": next_q,
            "reask_count": 0,
            "messages": [AIMessage(content=next_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 5: Imovel pronto - coletar forma de pagamento
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_pagamento":
        logger.info("BUYER | Coletando forma de pagamento | phone=%s", phone)

        pagamento = await _extract_field(
            effective_message,
            "forma de pagamento (a vista, financiamento, permuta, etc)",
        )

        if _is_off_topic(pagamento):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            pagamento = "nao informado"
        elif _is_missing(pagamento):
            pagamento = "nao informado"

        tags = await _save_tag(lead_id, tags, "forma_pagamento", pagamento)

        logger.info(
            "BUYER | Pagamento=%r | TAG: forma_pagamento | phone=%s", pagamento, phone
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        next_q, next_msg = await _advance_pronto_qualification(
            phone, tags, after_step="buyer_pronto_pagamento"
        )
        if next_q is None:
            next_q = "buyer_pronto_prioridades"
            next_msg = PRONTO_ASK_PRIORIDADES
            await send_whatsapp_message(phone, next_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": next_q,
            "reask_count": 0,
            "messages": [AIMessage(content=next_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 6: Imovel pronto - coletar urgencia
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_urgencia":
        logger.info("BUYER | Coletando urgencia | phone=%s", phone)

        urgencia = await _extract_field(
            effective_message,
            "prazo de TEMPO para fechar o negocio (ex: 30 dias, 3 meses, urgente). "
            "Se a mensagem for sobre forma de pagamento (a vista, financiamento, FGTS) "
            "sem mencionar prazo temporal, responda 'nao informado'",
        )

        if _is_off_topic(urgencia):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            urgencia = "nao informado"
        elif _is_missing(urgencia):
            urgencia = "nao informado"

        tags = await _save_tag(lead_id, tags, "urgencia", urgencia)

        logger.info(
            "BUYER | Urgencia=%r | TAG: urgencia | phone=%s", urgencia, phone
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        next_q, next_msg = await _advance_pronto_qualification(
            phone, tags, after_step="buyer_pronto_urgencia"
        )
        if next_q is None:
            next_q = "buyer_pronto_prioridades"
            next_msg = PRONTO_ASK_PRIORIDADES
            await send_whatsapp_message(phone, next_msg)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": next_q,
            "reask_count": 0,
            "messages": [AIMessage(content=next_msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7: Imovel pronto - coletar prioridades + calcular score
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_prioridades":
        logger.info("BUYER | Coletando prioridades e calculando score | phone=%s", phone)

        # Se prioridades já foi capturado (ex: via extrator proativo no greeting após timeout)
        prioridades = tags.get("prioridades") if _tag_collected(tags, "prioridades") else None

        if prioridades:
            logger.info(
                "BUYER | Prioridades ja capturado: %r (skip extracao) | phone=%s",
                prioridades, phone,
            )
        else:
            prioridades = await _extract_field(
                effective_message,
                "prioridades ou diferenciais mais importantes para o lead no imovel "
                "(seguranca, lazer, vista, privacidade, localizacao, etc)",
            )

            if _is_off_topic(prioridades):
                if reask_count < 2:
                    redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                    await send_whatsapp_message(phone, redirect_msg)
                    return {
                        "current_node": "buyer",
                        "tags": tags,
                        "last_question": last_question,
                        "awaiting_response": True,
                        "reask_count": reask_count + 1,
                    }
                prioridades = "nao informado"
            elif _is_missing(prioridades):
                prioridades = "nao informado"

            tags = await _save_tag(lead_id, tags, "prioridades", prioridades)

        logger.info(
            "BUYER | Prioridades=%r | TAG: prioridades | phone=%s", prioridades, phone
        )

        # Classificar categorias para o scoring
        investimento_categoria = await _classify_field(
            _CLASSIFY_INVESTIMENTO_PROMPT, tags.get("faixa_valor", "")
        )
        pagamento_categoria = await _classify_field(
            _CLASSIFY_PAGAMENTO_PROMPT, tags.get("forma_pagamento", "")
        )
        urgencia_categoria = await _classify_field(
            _CLASSIFY_URGENCIA_PROMPT, tags.get("urgencia", "")
        )
        situacao_categoria = await _classify_field(
            _CLASSIFY_SITUACAO_PROMPT, tags.get("situacao_imovel", "")
        )
        dados_preenchidos = _count_dados_preenchidos(tags)

        score_data = calculate_investor_score(
            {
                "investimento_categoria": investimento_categoria,
                "pagamento_categoria": pagamento_categoria,
                "urgencia_categoria": urgencia_categoria,
                "situacao_categoria": situacao_categoria,
                "dados_preenchidos": dados_preenchidos,
            }
        )

        total_score = score_data["total_score"]
        classification = score_data["classification"]
        nome_display = lead_name or tags.get("lead_identificado", "")

        logger.info(
            "BUYER | Score=%d | Classificacao=%s | Categorias: "
            "invest=%s pag=%s urg=%s sit=%s dados=%d | phone=%s",
            total_score,
            classification,
            investimento_categoria,
            pagamento_categoria,
            urgencia_categoria,
            situacao_categoria,
            dados_preenchidos,
            phone,
        )

        # Persistir score no banco
        if lead_id:
            async with async_session() as session:
                score_svc = ScoreService(session)
                await score_svc.upsert(
                    lead_id=lead_id,
                    score_type="buyer",
                    investimento_pts=score_data["investimento_pts"],
                    pagamento_pts=score_data["pagamento_pts"],
                    urgencia_pts=score_data["urgencia_pts"],
                    situacao_pts=score_data["situacao_pts"],
                    dados_pts=score_data["dados_pts"],
                )

            async with async_session() as session:
                lead_svc = LeadService(session)
                lead = await lead_svc.get_by_id(lead_id)
                if lead:
                    await lead_svc.update_classification(lead, classification, total_score)

        # Salvar classificação como tag para aparecer no CRM
        tags = await _save_tag(lead_id, tags, "classificacao_comprador", classification)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        stage_id = kommo.stage_id_for_classification(classification)
        if stage_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        base_state = {
            "current_node": "buyer",
            "tags": tags,
            "score_data": score_data,
            "total_score": total_score,
            "classification": classification,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "reask_count": 0,
        }

        # ----------------------------------------------------------------
        # Notificacao ao corretor baseada no score
        # QUENTE (85-100): SLA 2h | MORNO (60-84): SLA 24h | FRIO: sem notif
        # ----------------------------------------------------------------
        if lead_id:
            if classification == "quente":
                async with async_session() as session:
                    notif_svc = NotificationService(session)
                    await notif_svc.create(
                        lead_id=lead_id,
                        notification_type="corretor_urgente",
                        sla_hours=2,
                        payload={
                            "phone": phone,
                            "score": total_score,
                            "nome": nome_display,
                            "faixa_valor": tags.get("faixa_valor", ""),
                            "forma_pagamento": tags.get("forma_pagamento", ""),
                            "urgencia": tags.get("urgencia", ""),
                            "situacao_imovel": tags.get("situacao_imovel", ""),
                        },
                    )
                logger.info(
                    "BUYER | Notificacao corretor URGENTE (SLA 2h) criada "
                    "| phone=%s | score=%d",
                    phone,
                    total_score,
                )
            elif classification == "morno":
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
                            "faixa_valor": tags.get("faixa_valor", ""),
                            "forma_pagamento": tags.get("forma_pagamento", ""),
                            "urgencia": tags.get("urgencia", ""),
                        },
                    )
                logger.info(
                    "BUYER | Notificacao corretor PADRAO (SLA 24h) criada "
                    "| phone=%s | score=%d",
                    phone,
                    total_score,
                )

        # Todos os leads (quente/morno/frio) recebem apresentação de imóveis
        msg = PRONTO_APRESENTAR.format(nome=nome_display or "voce")
        await send_whatsapp_message(phone, msg)
        return {
            **base_state,
            "awaiting_response": True,
            "last_question": "buyer_pronto_preferencias",
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 8: Imovel pronto - coletar preferencias (regiao + suites)
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_preferencias":
        logger.info(
            "BUYER | Coletando preferencias (regiao + suites) | phone=%s", phone
        )

        regiao = await _extract_field(
            effective_message, "regiao ou bairro preferido em Cuiaba"
        )
        suites = await _extract_field(
            effective_message, "quantidade de suites desejadas"
        )

        # Reperguntar apenas se AMBOS os campos sao completamente off_topic
        if _is_off_topic(regiao) and _is_off_topic(suites):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }

        if _is_off_topic(regiao) or _is_missing(regiao):
            regiao = "nao informado"
        if _is_off_topic(suites) or _is_missing(suites):
            suites = "nao informado"

        # Mescla com dados parciais ja salvos (caso seja segunda passagem)
        if regiao == "nao informado" and tags.get("localizacao"):
            regiao = tags["localizacao"]
        if suites == "nao informado" and tags.get("suites_interesse"):
            suites = tags["suites_interesse"]

        tags = await _save_tag(lead_id, tags, "localizacao", regiao)
        tags = await _save_tag(lead_id, tags, "suites_interesse", suites)

        # Pergunta especifica pelo campo faltante (apenas na primeira tentativa)
        if reask_count == 0:
            if regiao == "nao informado" and suites != "nao informado":
                msg = "E em qual região ou bairro de Cuiabá você prefere?"
                logger.info("BUYER | Regiao faltando, pedindo especificamente | phone=%s", phone)
                await send_whatsapp_message(phone, msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": "buyer_pronto_preferencias",
                    "awaiting_response": True,
                    "reask_count": 1,
                    "messages": [AIMessage(content=msg)],
                }
            if suites == "nao informado" and regiao != "nao informado":
                msg = "Entendido! E quantas suítes você precisa?"
                logger.info("BUYER | Suites faltando, pedindo especificamente | phone=%s", phone)
                await send_whatsapp_message(phone, msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": "buyer_pronto_preferencias",
                    "awaiting_response": True,
                    "reask_count": 1,
                    "messages": [AIMessage(content=msg)],
                }

        regiao_display = regiao if regiao != "nao informado" else "Cuiaba"
        suites_display = suites if suites != "nao informado" else "sua necessidade"

        logger.info(
            "BUYER | Regiao=%r | Suites=%r | phone=%s",
            regiao, suites, phone,
        )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        # Enviar imóveis prontos que combinam com a região e suítes do comprador
        investimento_categoria_buyer = await _classify_field(
            _CLASSIFY_INVESTIMENTO_PROMPT, tags.get("faixa_valor", "")
        )
        async with async_session() as session:
            props_buyer = await search_properties(
                bairro=regiao if regiao != "nao informado" else "",
                situacao="Pronto",
                investimento_categoria=investimento_categoria_buyer,
                finalidade="Venda",
                session=session,
            )
        for prop in props_buyer[:2]:
            await send_whatsapp_message(phone, format_property_whatsapp(prop))

        msg = PRONTO_APRESENTAR_DETALHES
        await send_whatsapp_message(phone, msg)
        logger.info(
            "BUYER | %d imóvel(is) enviado(s) ao comprador | phone=%s",
            len(props_buyer[:2]),
            phone,
        )

        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "buyer_pronto_visita",
            "reask_count": 0,
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 9: Imovel pronto - verificar interesse em visita
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_visita":
        logger.info("BUYER | Verificando interesse em visita | phone=%s", phone)

        llm = _get_llm()
        visita_resp = await llm.ainvoke(_QUER_VISITA_PROMPT.format(message=effective_message))
        visita_raw = visita_resp.content.strip().lower()

        # Re-ask se resposta for completamente off-topic
        if "off_topic" in visita_raw:
            if reask_count < 2:
                logger.info(
                    "BUYER | Resposta visita off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }

        quer_visita = visita_raw.startswith("sim")

        if quer_visita:
            logger.info("BUYER | Lead quer visitar | phone=%s", phone)
            await send_whatsapp_message(phone, PRONTO_AGENDAR_VISITA)
            return {
                "current_node": "buyer",
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_pronto_data",
                "reask_count": 0,
                "messages": [AIMessage(content=PRONTO_AGENDAR_VISITA)],
            }

        # Nao quer visita agora -> identificar barreira (Secao 3.5 PDF)
        logger.info("BUYER | Lead nao quer visita agora -> identificando barreira | phone=%s", phone)
        await send_whatsapp_message(phone, PRONTO_ASK_BARREIRA)
        return {
            "current_node": "buyer",
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "buyer_pronto_barreira",
            "reask_count": 0,
            "messages": [AIMessage(content=PRONTO_ASK_BARREIRA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 10: Imovel pronto - coletar data/horario da visita
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_data":
        logger.info("BUYER | Coletando data da visita | phone=%s", phone)

        # Verificar se o lead informou apenas dia da semana (sem data especifica)
        llm = _get_llm()
        vague_resp = await llm.ainvoke(_VAGUE_DATE_PROMPT.format(message=effective_message))
        vague_day = vague_resp.content.strip().lower().rstrip(".")

        if vague_day in _WEEKDAY_MAP:
            weekday_num = _WEEKDAY_MAP[vague_day]
            d1, d2, d3 = _next_three_weekdays(weekday_num)
            day_label = _WEEKDAY_DISPLAY.get(vague_day, vague_day.capitalize())
            msg = (
                f"Qual das próximas {day_label}s fica melhor para você?\n\n"
                f"• {day_label} {d1}\n"
                f"• {day_label} {d2}\n"
                f"• {day_label} {d3}"
            )
            logger.info(
                "BUYER | Data vaga (%s) -> perguntando qual das 3 proximas | phone=%s",
                vague_day, phone,
            )
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_pronto_data_confirm",
                "messages": [AIMessage(content=msg)],
            }

        data_horario = await _extract_field(
            effective_message, "data, dia e horario/periodo preferidos para a visita"
        )

        if not _has_time_info(data_horario):
            tags["_visita_data_parcial"] = data_horario
            msg_hora = "Ótimo! E qual horário fica melhor para você? (ex: 10h, 14h, manhã ou tarde)"
            logger.info(
                "BUYER | Data sem horario (%r) -> pedindo horario | phone=%s",
                data_horario, phone,
            )
            await send_whatsapp_message(phone, msg_hora)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_pronto_horario",
                "messages": [AIMessage(content=msg_hora)],
            }

        return await _finalize_visit_scheduling(
            phone, lead_id, lead_name, tags, kommo, kommo_lead_id, kommo_contact_id, data_horario
        )

    # -----------------------------------------------------------------------
    # Etapa 10b: Confirmacao da data especifica (apos clarificacao de dia vago)
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_data_confirm":
        logger.info("BUYER | Confirmando data especifica da visita | phone=%s", phone)

        data_horario = await _extract_field(
            effective_message, "data, dia e horario/periodo preferidos para a visita"
        )

        if not _has_time_info(data_horario):
            tags["_visita_data_parcial"] = data_horario
            msg_hora = "Ótimo! E qual horário fica melhor para você? (ex: 10h, 14h, manhã ou tarde)"
            logger.info(
                "BUYER | Data confirmada sem horario (%r) -> pedindo horario | phone=%s",
                data_horario, phone,
            )
            await send_whatsapp_message(phone, msg_hora)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_pronto_horario",
                "messages": [AIMessage(content=msg_hora)],
            }

        return await _finalize_visit_scheduling(
            phone, lead_id, lead_name, tags, kommo, kommo_lead_id, kommo_contact_id, data_horario
        )

    # -----------------------------------------------------------------------
    # Etapa 10c: Coleta de horario da visita (apos data sem horario)
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_horario":
        logger.info("BUYER | Coletando horario da visita | phone=%s", phone)

        horario = await _extract_field(
            effective_message,
            "horário ou período para a visita (manhã, tarde, hora específica como 10h ou 14h30)",
        )
        data_parcial = tags.pop("_visita_data_parcial", "")

        if _is_off_topic(horario) or _is_missing(horario):
            data_horario = data_parcial
        else:
            data_horario = f"{data_parcial} às {horario}" if data_parcial else horario

        logger.info(
            "BUYER | Data+hora final: %r | phone=%s", data_horario, phone
        )
        return await _finalize_visit_scheduling(
            phone, lead_id, lead_name, tags, kommo, kommo_lead_id, kommo_contact_id, data_horario
        )

    # -----------------------------------------------------------------------
    # Etapa 11: Imovel pronto - identificar e tratar barreira (Secao 3.5 PDF)
    # -----------------------------------------------------------------------
    if last_question == "buyer_pronto_barreira":
        logger.info("BUYER | Identificando barreira | phone=%s", phone)

        llm = _get_llm()
        barreira_resp = await llm.ainvoke(
            _BARREIRA_PROMPT.format(message=effective_message)
        )
        barreira = barreira_resp.content.strip().lower()

        # Re-ask se resposta for completamente off-topic (nao menciona barreira nenhuma)
        if "off_topic" in barreira:
            if reask_count < 2:
                logger.info(
                    "BUYER | Barreira off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "buyer",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }

        # Normalizar para categoria valida
        if "financ" in barreira:
            barreira = "financeira"
        elif "timing" in barreira or "momento" in barreira:
            barreira = "timing"
        else:
            barreira = "conhecimento"

        logger.info(
            "BUYER | Barreira identificada: %r | phone=%s", barreira, phone
        )

        nome_display = lead_name or tags.get("lead_identificado", "")

        if barreira == "financeira":
            tags = await _save_tag(lead_id, tags, "consultoria_agendada", "true")
            await send_whatsapp_message(phone, PRONTO_BARREIRA_FINANCEIRA)

            if lead_id:
                async with async_session() as session:
                    notif_svc = NotificationService(session)
                    await notif_svc.create(
                        lead_id=lead_id,
                        notification_type="corretor_padrao",
                        sla_hours=24,
                        payload={
                            "phone": phone,
                            "nome": nome_display,
                            "barreira": "financeira",
                            "faixa_valor": tags.get("faixa_valor", ""),
                            "forma_pagamento": tags.get("forma_pagamento", ""),
                            "tipo": "consultoria_financeira",
                        },
                    )
                logger.info(
                    "BUYER | TAG: consultoria_agendada | notif corretor_padrao (24h) | phone=%s",
                    phone,
                )

            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "buyer_barreira_financeira_resp",
                "reask_count": 0,
                "messages": [AIMessage(content=PRONTO_BARREIRA_FINANCEIRA)],
            }

        if barreira == "timing":
            tags = await _save_tag(lead_id, tags, "lista_vip", "true")
            await send_whatsapp_message(phone, PRONTO_BARREIRA_TIMING)

            if lead_id:
                async with async_session() as session:
                    job_svc = JobService(session)
                    await job_svc.schedule_after(
                        lead_id=lead_id,
                        job_type="nurture_30d",
                        delay=timedelta(days=30),
                        payload={
                            "phone": phone,
                            "nome": nome_display,
                            "tipo": "lista_vip_pronto",
                        },
                    )
                logger.info(
                    "BUYER | TAG: lista_vip | nurture_30d agendado | phone=%s", phone
                )

            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            return {
                "current_node": "buyer",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": False,
                "last_question": "buyer_encerrado",
                "messages": [AIMessage(content=PRONTO_BARREIRA_TIMING)],
            }

        # conhecimento -> convidar para showroom
        tags = await _save_tag(lead_id, tags, "tour_agendado", "true")
        await send_whatsapp_message(phone, PRONTO_BARREIRA_CONHECIMENTO)

        if lead_id:
            async with async_session() as session:
                notif_svc = NotificationService(session)
                await notif_svc.create(
                    lead_id=lead_id,
                    notification_type="corretor_padrao",
                    sla_hours=24,
                    payload={
                        "phone": phone,
                        "nome": nome_display,
                        "barreira": "conhecimento",
                        "tipo": "tour_showroom",
                    },
                )
            logger.info(
                "BUYER | TAG: tour_agendado | notif corretor_padrao (24h) | phone=%s",
                phone,
            )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        if kommo_lead_id:
            stage_id = settings.kommo_stage_map_dict.get("avaliacao_agendada")
            if stage_id:
                await kommo.update_lead_stage(kommo_lead_id, stage_id)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "buyer_barreira_conhecimento_resp",
            "reask_count": 0,
            "messages": [AIMessage(content=PRONTO_BARREIRA_CONHECIMENTO)],
        }

    # -----------------------------------------------------------------------
    # Etapa: Barreira financeira - lead respondeu, encerrar fluxo
    # -----------------------------------------------------------------------
    if last_question == "buyer_barreira_financeira_resp":
        logger.info("BUYER | Encerrando fluxo barreira financeira | phone=%s", phone)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg_enc = (
            "Nosso consultor já recebeu suas informações e vai entrar em contato "
            "para confirmar tudo. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_enc)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": "buyer_encerrado",
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Etapa: Barreira conhecimento - lead respondeu data do tour, encerrar
    # -----------------------------------------------------------------------
    if last_question == "buyer_barreira_conhecimento_resp":
        logger.info("BUYER | Encerrando fluxo barreira conhecimento | phone=%s", phone)

        data_tour = await _extract_field(
            effective_message, "data e horario do tour ou visita informados pelo lead"
        )
        if data_tour and data_tour != "nao informado":
            tags = await _save_tag(lead_id, tags, "data_tour", data_tour)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg_enc = (
            "Nosso consultor já recebeu suas informações e vai entrar em contato "
            "para confirmar tudo. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_enc)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": "buyer_encerrado",
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Etapa: Lead fora do perfil confirmou querer o contato -> enviar e encerrar
    # -----------------------------------------------------------------------
    if last_question == "buyer_fora_perfil_resp":
        logger.info("BUYER | Enviando contato parceiro (fora perfil) | phone=%s", phone)
        await send_whatsapp_message(phone, BUYER_FORA_PERFIL_CONTATO)
        return {
            "current_node": "buyer",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": "buyer_encerrado",
            "messages": [AIMessage(content=BUYER_FORA_PERFIL_CONTATO)],
        }

    # -----------------------------------------------------------------------
    # Fallback: estado desconhecido - NAO reiniciar, rotear para completed
    # -----------------------------------------------------------------------
    logger.warning(
        "BUYER | Estado desconhecido last_question=%r - roteando p/ completed | phone=%s",
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
        "is_silenced": False,  # deixa o completed_node enviar o handoff
    }
