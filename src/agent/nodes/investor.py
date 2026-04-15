"""
investor.py - Node do fluxo de investidor (Feature 12).

Coleta progressiva de dados em 5 perguntas agrupadas, calcula o score
do lead (0-100 pts) e age de acordo com a classificacao:

  QUENTE (85-100) -> envia opcoes, agenda visita com consultor
  MORNO  (60-84)  -> selecao personalizada, pede contato, oferece consultoria
  FRIO   (0-59)   -> identifica barreiras, agenda nutricao 30/60/90d

Etapas (rastreadas por last_question):
  1. Primeira chamada (current_node != "investor")
         -> INVESTOR_INITIAL (pergunta estrategia)
         -> last_question = "investor_estrategia"

  2. investor_estrategia
         -> TAG: investidor_yield | investidor_valorizacao
         -> INVESTOR_ASK_TIPO_NOME
         -> last_question = "investor_tipo_nome"

  3. investor_tipo_nome
         -> TAG: lead_tipo_imovel, lead_identificado
         -> INVESTOR_ASK_REGIAO
         -> last_question = "investor_regiao"

  4. investor_regiao
         -> TAG: localizacao, faixa_investimento
         -> INVESTOR_ASK_NECESSIDADES
         -> last_question = "investor_necessidades"

  5. investor_necessidades
         -> TAG: necessidades, vagas_garagem, situacao_imovel
         -> INVESTOR_ASK_FINALIZACAO
         -> last_question = "investor_finalizacao"

  6. investor_finalizacao
         -> TAG: forma_pagamento
         -> last_question = "investor_prazo"

  6b. investor_prazo
         -> TAG: urgencia
         -> last_question = "investor_prioridades"

  6c. investor_prioridades
         -> TAG: prioridades
         -> Calcula score e age por classificacao:
              QUENTE -> last_question = "investor_quente_visita"
              MORNO  -> last_question = "investor_morno_contato"
              FRIO   -> nutricao agendada, awaiting_response = False

  7a. investor_quente_visita
         -> Quer visita -> TAG: visita_agendada, notifica corretor (SLA 2h)
         -> Quer mais opcoes -> TAG: consultoria_agendada
         -> awaiting_response = False

  7b. investor_morno_contato
         -> Extrai contato, TAG: consultoria_agendada | dica_vip
         -> Notifica corretor (SLA 24h)
         -> awaiting_response = False
"""

import asyncio
import uuid
from datetime import timedelta

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent.prompts.investor import (
    INVESTOR_ASK_FINALIZACAO,
    INVESTOR_ASK_INVESTIMENTO,
    INVESTOR_ASK_NECESSIDADES,
    INVESTOR_ASK_NOME,
    INVESTOR_ASK_PRAZO,
    INVESTOR_ASK_PRIORIDADES,
    INVESTOR_ASK_REGIAO,
    INVESTOR_ASK_SITUACAO,
    INVESTOR_ASK_TIPO_NOME,
    INVESTOR_ASK_VAGAS,
    INVESTOR_FRIO_BARREIRA,
    INVESTOR_FRIO_CONHECIMENTO,
    INVESTOR_FRIO_CONTATO_PARCEIRO,
    INVESTOR_FRIO_FINANCEIRA,
    INVESTOR_FRIO_NUTRICAO,
    INVESTOR_FRIO_PARCEIRO,
    INVESTOR_FRIO_TIMING,
    INVESTOR_INITIAL,
    INVESTOR_MORNO_ASK_EMAIL,
    INVESTOR_MORNO_ASK_WHATS,
    INVESTOR_MORNO_CONSULTORIA,
    INVESTOR_MORNO_DICA_VIP,
    INVESTOR_MORNO_SELECAO,
    INVESTOR_QUENTE_ASK_VISITA,
    INVESTOR_QUENTE_MAIS_OPCOES,
    INVESTOR_QUENTE_NAO_GOSTOU,
    INVESTOR_QUENTE_NOVAS_OPCOES,
    INVESTOR_QUENTE_OPCOES,
    INVESTOR_QUENTE_VISITA_CONFIRMADA,
)
from src.agent.prompts.fallback import (
    TECHNICAL_ERROR_MESSAGE,
    build_redirect_message,
    build_smart_redirect,
    get_last_bot_message,
    is_clarification,
    is_faq_question,
)
from src.agent.scoring.investor_score import calculate_investor_score
from src.agent.state import AgentState
from src.agent.tools.uazapi import send_whatsapp_message
from src.config.settings import settings
from src.properties.catalog import search_properties
from src.properties.formatter import format_property_whatsapp
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

_CLASSIFY_ESTRATEGIA_PROMPT = """Voce e um especialista em qualificacao de investidores imobiliarios.
Analise a mensagem do lead e identifique qual e o objetivo principal do investimento.

Objetivos possiveis:
- "yield": O lead busca RENDA PASSIVA com aluguel. Sinais: menciona aluguel, renda mensal,
  retorno mensal, inquilino, fluxo de caixa, rendimento, passivo, renda extra.
- "valorizacao": O lead busca GANHO DE CAPITAL na revenda. Sinais: menciona valorizacao,
  revenda, vender depois, ganho futuro, retorno no longo prazo, comprar e vender,
  medio/longo prazo, portfolio, diversificacao patrimonial.
- "off_topic": Resposta completamente fora do contexto — pergunta, assunto diferente, texto sem sentido.

Regras:
- Se o lead mencionar os dois objetivos, escolha o que aparecer com mais enfase.
- Se nao for possivel identificar claramente entre yield e valorizacao, classifique como "yield" (mais comum).
- Use "off_topic" APENAS quando a mensagem for completamente irrelevante para o contexto de investimento.
- Responda APENAS com uma palavra: "yield", "valorizacao" ou "off_topic".

Mensagem do lead: {message}

Classificacao:"""

_CLASSIFY_INVESTIMENTO_PROMPT = (
    "Classifique a faixa de investimento na categoria correta. "
    "Valor informado: {valor}\n\n"
    "IMPORTANTE: Se o valor informado NAO for um valor monetario explicito "
    "(ex: menciona suites, vagas, forma de pagamento, preferencias de imovel, "
    "prazos, ou qualquer coisa que nao seja um numero em reais/milhoes/mil), "
    "responda OBRIGATORIAMENTE 'nao_informado'.\n\n"
    "Categorias validas:\n"
    "- acima_2m: Acima de R$2.000.000\n"
    "- 1m_2m: Entre R$1.000.000 e R$2.000.000\n"
    "- 500k_1m: Entre R$500.000 e R$1.000.000\n"
    "- 400k_500k: Entre R$400.000 e R$500.000\n"
    "- abaixo_400k: Abaixo de R$400.000 (apenas se o lead informar um valor monetario claramente abaixo de 400k)\n"
    "- nao_informado: Valor nao informado, nao e monetario, ou nao foi possivel identificar\n\n"
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

_CLASSIFY_BARREIRA_FRIO_PROMPT = (
    "Voce e um especialista em qualificacao de leads imobiliarios.\n"
    "Analise a mensagem do lead e identifique qual e a principal barreira que impede o avanco.\n\n"
    "Categorias:\n"
    "- 'financeira': Lead menciona orcamento, preco alto, falta de dinheiro, financiamento, "
    "custo, valor, parcela, credito, nao tenho recursos, precisa organizar financas.\n"
    "- 'timing': Lead menciona tempo, nao e o momento, ainda nao, depois, mais pra frente, "
    "sem pressa, aguardando, situacao pessoal/profissional, mudanca de planos, prazo longo.\n"
    "- 'conhecimento': Lead quer saber mais sobre o mercado, comparar opcoes, entender melhor, "
    "pesquisar mais, ver mais imoveis, nao conhece a regiao, quer mais informacoes.\n\n"
    "Regras:\n"
    "- Na duvida entre 'timing' e 'financeira', escolha 'financeira'.\n"
    "- Na duvida entre 'timing' e 'conhecimento', escolha 'timing'.\n"
    "- Responda APENAS com uma palavra: 'financeira', 'timing' ou 'conhecimento'.\n\n"
    "Mensagem do lead: {valor}\n\n"
    "Barreira:"
)

_CLASSIFY_CONTATO_TIPO_PROMPT = (
    "O lead quer receber a selecao de imoveis por qual meio?\n"
    "Mensagem: {valor}\n\n"
    "Opcoes:\n"
    "- 'email': Lead menciona email, e-mail, correio eletronico\n"
    "- 'whatsapp': Lead menciona WhatsApp, zap, wpp, esse numero, pode mandar aqui, aqui mesmo\n"
    "- 'indefinido': Nao foi possivel identificar\n\n"
    "Responda APENAS com uma palavra: 'email', 'whatsapp' ou 'indefinido'."
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

_CLASSIFY_REACAO_QUENTE_PROMPT = """Voce e um especialista em qualificacao de leads imobiliarios.
Analise a reacao do lead apos receber opcoes de imoveis exclusivos e classifique em uma das tres categorias:

- "gostou": Lead demonstra entusiasmo, interesse claro, quer ver as opcoes, confirma interesse,
  diz "sim", "quero ver", "manda", "adorei", "que otimo", "pode ser", "aceito", "vamos".

- "interessado": Lead esta curioso mas hesitante, quer mais informacoes antes de decidir,
  faz perguntas sobre preco ou detalhes, pede mais opcoes, diz "depende", "me conta mais",
  "quero saber mais", "quanto custa", "que tipo de imovel".

- "nao_gostou": Lead demonstra desinteresse, recusa, quer parar a conversa,
  diz "nao", "nao tenho interesse", "nao e o momento", "nao quero", "nao preciso".

Regras:
- Na duvida entre "gostou" e "interessado", classifique como "gostou" (dar beneficio da duvida).
- Na duvida entre "interessado" e "nao_gostou", classifique como "interessado".
- Responda APENAS com uma palavra: "gostou", "interessado" ou "nao_gostou".

Mensagem do lead: {message}

Classificacao:"""

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


def _get_qualifier_llm() -> ChatOpenAI:
    """LLM de alta capacidade para qualificacao de estrategia do investidor."""
    return ChatOpenAI(
        model="gpt-5.4",
        temperature=0,
        api_key=settings.openai_api_key,
        timeout=30,
    )


def _get_reaction_llm() -> ChatOpenAI:
    """LLM para classificar reacoes e barreiras (routers do fluxo investor)."""
    return ChatOpenAI(
        model="gpt-5.4",
        api_key=settings.openai_api_key,
        timeout=30,
    )


def _is_off_topic(value: str) -> bool:
    """Mensagem completamente fora do contexto (off_topic)."""
    return value.strip().lower() == "off_topic"


def _is_missing(value: str) -> bool:
    """Campo relevante mas nao fornecido — aceitar e seguir."""
    return value.strip().lower() in ("nao informado", "nao_informado")


async def _classify_barreira_frio(message: str) -> str:
    """Classifica a barreira do lead frio em 'financeira', 'timing' ou 'conhecimento'."""
    llm = _get_reaction_llm()
    prompt = _CLASSIFY_BARREIRA_FRIO_PROMPT.format(valor=message)
    response = await llm.ainvoke(prompt)
    raw = response.content.strip().lower().split()[0].strip("\"'.,;:")
    if raw in ("financeira", "timing", "conhecimento"):
        return raw
    return "timing"  # fallback conservador


async def _classify_reacao_quente(message: str) -> str:
    """Classifica a reacao do lead quente em 'gostou', 'interessado' ou 'nao_gostou'."""
    llm = _get_reaction_llm()
    prompt = _CLASSIFY_REACAO_QUENTE_PROMPT.format(message=message)
    response = await llm.ainvoke(prompt)
    raw = response.content.strip().lower().split()[0].strip("\"'.,;:")
    if raw in ("gostou", "interessado", "nao_gostou"):
        return raw
    return "interessado"  # fallback conservador


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


def _is_abaixo_400k(investimento_categoria: str, faixa_valor: str = "") -> bool:
    """Retorna True APENAS se o lead informou explicitamente um valor monetário abaixo de 400k.
    Evita falsos positivos quando faixa_valor contém texto não-monetário.
    """
    if investimento_categoria != "abaixo_400k":
        return False
    # Segurança extra: exige que faixa_valor contenha ao menos um dígito
    # (evita classificar "vou financiar", "2 suítes", etc. como abaixo_400k)
    raw = faixa_valor.strip().lower()
    if not raw or raw in ("nao informado", "nao_informado"):
        return False
    return any(ch.isdigit() for ch in raw)


async def _notify_corretor_morno(phone: str, tags: dict, total_score: int) -> None:
    """Envia email ao corretor quando lead MORNO entra em follow-up programado (SLA 24h)."""
    from datetime import datetime, timezone, timedelta
    cuiaba_tz = timezone(timedelta(hours=-4))
    data_selecao = datetime.now(tz=cuiaba_tz).strftime("%d/%m/%Y às %H:%M")

    perfil = tags.get("imoveis_apresentados") or tags.get("lead_tipo_imovel", "")

    result = await EmailService().send_investor_morno_followup_notification(
        lead_name=tags.get("lead_identificado", ""),
        lead_phone=phone,
        score=total_score,
        perfil=perfil,
        data_selecao=data_selecao,
    )
    logger.info(
        "INVESTOR | Email corretor morno follow-up | status=%s | phone=%s",
        result.get("status"),
        phone,
    )


async def _notify_corretor_frio(
    phone: str,
    tags: dict,
    total_score: int,
    barreira: str = "",
    estrategia: str = "",
) -> None:
    """Envia email ao sistema quando lead FRIO entra em nutrição ativa (Revisão: 30 dias)."""
    from datetime import datetime, timezone, timedelta
    cuiaba_tz = timezone(timedelta(hours=-4))
    data_entrada = datetime.now(tz=cuiaba_tz).strftime("%d/%m/%Y às %H:%M")

    perfil = tags.get("imoveis_apresentados") or tags.get("lead_tipo_imovel", "")

    result = await EmailService().send_investor_frio_notification(
        lead_name=tags.get("lead_identificado", ""),
        lead_phone=phone,
        score=total_score,
        perfil=perfil,
        data_entrada=data_entrada,
        barreira=barreira,
        estrategia=estrategia,
    )
    logger.info(
        "INVESTOR | Email sistema frio nutricao | status=%s | barreira=%s | phone=%s",
        result.get("status"),
        barreira,
        phone,
    )


async def _notify_corretor_visita(phone: str, tags: dict, total_score: int) -> None:
    """Envia email ao corretor quando visita de lead quente investidor e confirmada."""
    imoveis = tags.get("imoveis_apresentados") or tags.get("lead_tipo_imovel", "")
    result = await EmailService().send_investor_corretor_notification(
        lead_name=tags.get("lead_identificado", ""),
        lead_phone=phone,
        lead_email=tags.get("email_lead", ""),
        score=total_score,
        tipo_imovel=imoveis,
        regiao=tags.get("localizacao", ""),
        budget=tags.get("faixa_valor", ""),
        data_visita=tags.get("data_visita", ""),
    )
    logger.info(
        "INVESTOR | Email corretor visita | status=%s | phone=%s",
        result.get("status"),
        phone,
    )


# ---------------------------------------------------------------------------
# Node principal
# ---------------------------------------------------------------------------


async def investor_node(state: AgentState) -> dict:
    """
    Node: Fluxo de investidor com sistema de score (Feature 12).

    Consulte o docstring do modulo para detalhes de cada etapa.
    """
    phone = state["phone"]
    try:
        return await _investor_node_impl(state)
    except Exception as exc:
        logger.exception("INVESTOR | Erro inesperado | phone=%s | erro=%s", phone, str(exc))
        try:
            await send_whatsapp_message(phone, TECHNICAL_ERROR_MESSAGE)
        except Exception:
            logger.exception("INVESTOR | Falha ao enviar fallback | phone=%s", phone)
        return {
            "current_node": state.get("current_node", "investor"),
            "last_question": state.get("last_question"),
            "awaiting_response": True,
            "tags": state.get("tags") or {},
            "reask_count": state.get("reask_count", 0),
        }


async def _investor_node_impl(state: AgentState) -> dict:
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
    total_score = state.get("total_score", 0)
    kommo = KommoService()
    last_bot_message = get_last_bot_message(state.get("messages") or [])

    # Extração proativa: captura qualquer informação útil mencionada pelo lead
    tags = await extract_context_from_message(effective_message, tags, lead_id)

    # FAQ: lead perguntou sobre a empresa ou processos → encaminhar para FAQ
    if is_faq_question(effective_message):
        logger.info("INVESTOR | FAQ detectado em fluxo ativo | phone=%s", phone)
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
        logger.info("INVESTOR | Clarificacao detectada | lq=%s | phone=%s", last_question, phone)
        redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
        await send_whatsapp_message(phone, redirect_msg)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "last_question": last_question,
            "awaiting_response": True,
            "reask_count": reask_count,
        }

    # -----------------------------------------------------------------------
    # Etapa 1: Primeira chamada (vinda do router)
    # Nota: se last_question já tem prefixo "investor_", é retorno de FAQ — não reinicia.
    # -----------------------------------------------------------------------
    if current_node != "investor" and not (last_question and last_question.startswith("investor_")):
        logger.info("INVESTOR | Iniciando fluxo de investidor | phone=%s", phone)
        await send_whatsapp_message(phone, INVESTOR_INITIAL)
        return {
            "current_node": "investor",
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_estrategia",
            "messages": [AIMessage(content=INVESTOR_INITIAL)],
        }

    # -----------------------------------------------------------------------
    # Etapa 2: Capturou estrategia, perguntar tipo de imovel
    # -----------------------------------------------------------------------
    if last_question == "investor_estrategia":
        logger.info("INVESTOR | Qualificando estrategia de investimento | phone=%s", phone)

        llm = _get_qualifier_llm()
        estrategia_resp = await llm.ainvoke(
            _CLASSIFY_ESTRATEGIA_PROMPT.format(message=effective_message)
        )
        estrategia = estrategia_resp.content.strip().lower()

        # Re-ask se resposta for completamente off-topic (ate 2 tentativas)
        if "off_topic" in estrategia:
            if reask_count < 2:
                logger.info(
                    "INVESTOR | Estrategia off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg or INVESTOR_INITIAL)
                return {
                    "current_node": "investor",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            # Apos 2 tentativas, assume yield como fallback
            estrategia = "yield"

        if "valorizacao" in estrategia:
            tags = await _save_tag(lead_id, tags, "investidor_valorizacao", "true")
            logger.info("INVESTOR | Estrategia: valorizacao | phone=%s", phone)
        else:
            tags = await _save_tag(lead_id, tags, "investidor_yield", "true")
            logger.info("INVESTOR | Estrategia: yield (aluguel) | phone=%s", phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
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
    # Etapa 3: Capturou tipo, pausa natural e pergunta o nome
    # -----------------------------------------------------------------------
    if last_question == "investor_tipo_nome":
        logger.info("INVESTOR | Capturando tipo de imovel | phone=%s", phone)

        tipo = await _extract_field(
            effective_message,
            "tipo ou estilo do imovel (apartamento, casa, cobertura, etc)",
        )

        if _is_off_topic(tipo):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "investor",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            tipo = "nao informado"
        elif _is_missing(tipo):
            tipo = "nao informado"

        tags = await _save_tag(lead_id, tags, "lead_tipo_imovel", tipo)

        logger.info("INVESTOR | Tipo=%r | phone=%s", tipo, phone)

        # Pausa natural antes de perguntar o nome
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await asyncio.sleep(5)
        await send_whatsapp_message(phone, INVESTOR_ASK_NOME)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_nome",
            "reask_count": 0,
            "messages": [AIMessage(content=INVESTOR_ASK_NOME)],
        }

    # -----------------------------------------------------------------------
    # Etapa 3b: Capturou nome, perguntar regiao + investimento
    # -----------------------------------------------------------------------
    if last_question == "investor_nome":
        logger.info("INVESTOR | Capturando nome | phone=%s", phone)

        nome = await _extract_field(
            effective_message, "nome ou como o lead quer ser chamado"
        )

        if _is_off_topic(nome):
            if reask_count < 2:
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "investor",
                    "tags": tags,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            nome = "nao informado"
        elif _is_missing(nome):
            nome = "nao informado"

        tags = await _save_tag(lead_id, tags, "lead_identificado", nome)

        nome_exibir = nome if nome != "nao informado" else (lead_name or "")

        logger.info("INVESTOR | Nome=%r | phone=%s", nome_exibir, phone)

        msg = INVESTOR_ASK_REGIAO.format(nome=nome_exibir or "")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "investor",
            "tags": tags,
            "lead_name": nome_exibir or lead_name,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_regiao",
            "reask_count": 0,
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 4: Capturou regiao, pausa e pergunta faixa de investimento
    # -----------------------------------------------------------------------
    if last_question == "investor_regiao":
        logger.info("INVESTOR | Capturando regiao | phone=%s", phone)

        raw_msg = effective_message.strip()
        # Mensagem curta (até 80 chars): é a própria região — usar direto sem LLM
        if len(raw_msg) <= 80 and not _is_off_topic(raw_msg) and not _is_missing(raw_msg):
            regiao = raw_msg
        else:
            regiao = await _extract_field(raw_msg, "regiao ou bairro de preferencia")
            if _is_off_topic(regiao):
                # Fallback: usa mensagem bruta se for pequena o suficiente
                regiao = raw_msg[:100] if len(raw_msg) <= 100 else "nao informado"
        tags = await _save_tag(lead_id, tags, "localizacao", regiao)

        logger.info("INVESTOR | Regiao=%r | phone=%s", regiao, phone)

        nome_exibir = lead_name or tags.get("lead_identificado", "")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await asyncio.sleep(5)
        msg = INVESTOR_ASK_INVESTIMENTO.format(nome=nome_exibir or "")
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_investimento",
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 4b: Capturou investimento, perguntar necessidades
    # -----------------------------------------------------------------------
    if last_question == "investor_investimento":
        logger.info("INVESTOR | Capturando faixa de investimento | phone=%s", phone)

        raw_inv = effective_message.strip()
        if len(raw_inv) <= 80 and not _is_off_topic(raw_inv) and not _is_missing(raw_inv):
            investimento = raw_inv
        else:
            investimento = await _extract_field(raw_inv, "faixa ou valor de investimento disponivel")
            if _is_off_topic(investimento):
                investimento = raw_inv[:100] if len(raw_inv) <= 100 else "nao informado"
        tags = await _save_tag(lead_id, tags, "faixa_valor", investimento)

        logger.info("INVESTOR | Investimento=%r | phone=%s", investimento, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, INVESTOR_ASK_NECESSIDADES)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_necessidades",
            "messages": [AIMessage(content=INVESTOR_ASK_NECESSIDADES)],
        }

    # -----------------------------------------------------------------------
    # Etapa 5: Capturou suites/preferencias, pausa 15s e pergunta vagas
    # -----------------------------------------------------------------------
    if last_question == "investor_necessidades":
        logger.info("INVESTOR | Capturando suites e preferencias | phone=%s", phone)

        necessidades = await _extract_field(
            effective_message,
            "necessidades do imovel (suites, closet, cinema, gourmet, etc)",
        )
        tags = await _save_tag(lead_id, tags, "necessidades", necessidades)

        logger.info("INVESTOR | Necessidades=%r | phone=%s", necessidades, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await asyncio.sleep(15)
        await send_whatsapp_message(phone, INVESTOR_ASK_VAGAS)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_vagas",
            "messages": [AIMessage(content=INVESTOR_ASK_VAGAS)],
        }

    # -----------------------------------------------------------------------
    # Etapa 5b: Capturou vagas, perguntar situacao (pronto vs lancamento)
    # -----------------------------------------------------------------------
    if last_question == "investor_vagas":
        logger.info("INVESTOR | Capturando vagas de garagem | phone=%s", phone)

        vagas = await _extract_field(
            effective_message, "quantidade de vagas de garagem desejadas"
        )
        tags = await _save_tag(lead_id, tags, "vagas_garagem", vagas)

        logger.info("INVESTOR | Vagas=%r | phone=%s", vagas, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, INVESTOR_ASK_SITUACAO)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_situacao",
            "messages": [AIMessage(content=INVESTOR_ASK_SITUACAO)],
        }

    # -----------------------------------------------------------------------
    # Etapa 5c: Capturou situacao, perguntar finalizacao
    # -----------------------------------------------------------------------
    if last_question == "investor_situacao":
        logger.info("INVESTOR | Capturando situacao do imovel | phone=%s", phone)

        situacao = await _extract_field(
            effective_message,
            "preferencia de situacao do imovel (pronto para morar, lancamento ou tanto faz)",
        )
        tags = await _save_tag(lead_id, tags, "situacao_imovel", situacao)

        logger.info("INVESTOR | Situacao=%r | phone=%s", situacao, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        # Lead veio do fluxo de permuta: forma de pagamento já é conhecida — pular INVESTOR_ASK_FINALIZACAO
        if tags.get("lead_permuta") == "true":
            tags = await _save_tag(lead_id, tags, "forma_pagamento", "permuta")
            nome_exibir = lead_name or tags.get("lead_identificado", "")
            msg = INVESTOR_ASK_PRAZO.format(nome=nome_exibir or "")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            logger.info(
                "INVESTOR | Permuta detectada -> pulando INVESTOR_ASK_FINALIZACAO | phone=%s", phone
            )
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_prazo",
                "messages": [AIMessage(content=msg)],
            }

        await asyncio.sleep(5)
        await send_whatsapp_message(phone, INVESTOR_ASK_FINALIZACAO)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_finalizacao",
            "messages": [AIMessage(content=INVESTOR_ASK_FINALIZACAO)],
        }

    # -----------------------------------------------------------------------
    # Etapa 6: Capturou pagamento, perguntar prazo
    # -----------------------------------------------------------------------
    if last_question == "investor_finalizacao":
        logger.info("INVESTOR | Capturando forma de pagamento | phone=%s", phone)

        pagamento = await _extract_field(
            effective_message,
            "forma de pagamento (a vista, financiamento, permuta, etc)",
        )
        tags = await _save_tag(lead_id, tags, "forma_pagamento", pagamento)

        logger.info("INVESTOR | Pagamento=%r | phone=%s", pagamento, phone)

        nome_exibir = lead_name or tags.get("lead_identificado", "")
        msg = INVESTOR_ASK_PRAZO.format(nome=nome_exibir or "")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_prazo",
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 6b: Capturou prazo -> perguntar prioridades
    # -----------------------------------------------------------------------
    if last_question == "investor_prazo":
        logger.info("INVESTOR | Capturando prazo | phone=%s", phone)

        urgencia = await _extract_field(
            effective_message,
            "prazo de TEMPO para fechar o negocio (ex: 30 dias, 3 meses, urgente, sem pressa). "
            "Se a mensagem mencionar caracteristicas do imovel, diferenciais, seguranca, lazer, "
            "localizacao ou qualquer preferencia que NAO seja prazo de tempo, responda 'off_topic'. "
            "Se for sobre forma de pagamento sem prazo temporal, responda 'nao informado'.",
        )

        if _is_off_topic(urgencia):
            if reask_count < 2:
                logger.info(
                    "INVESTOR | Prazo off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "investor",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            urgencia = "nao informado"

        tags = await _save_tag(lead_id, tags, "urgencia", urgencia)

        logger.info("INVESTOR | Urgencia=%r | phone=%s", urgencia, phone)

        nome_exibir = lead_name or tags.get("lead_identificado", "")
        msg = INVESTOR_ASK_PRIORIDADES.format(nome=nome_exibir or "")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, msg)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_prioridades",
            "reask_count": 0,
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 6c: Capturou prioridades -> calcular score
    # -----------------------------------------------------------------------
    if last_question == "investor_prioridades":
        logger.info("INVESTOR | Capturando prioridades e calculando score | phone=%s", phone)

        prioridades = await _extract_field(
            effective_message,
            "prioridades ou diferenciais essenciais do imovel "
            "(ex: seguranca 24h, lazer, piscina, academia, localizacao, vista, privacidade, etc). "
            "Se a mensagem for uma confirmacao generica ('sim', 'pode', 'ok', 'claro'), "
            "uma pergunta, ou nao mencionar nenhuma caracteristica de imovel, responda 'off_topic'.",
        )

        if _is_off_topic(prioridades):
            if reask_count < 2:
                logger.info(
                    "INVESTOR | Prioridades off_topic -> re-perguntando | reask=%d | phone=%s",
                    reask_count, phone,
                )
                redirect_msg = await build_smart_redirect(effective_message, last_question, last_bot_message)
                await send_whatsapp_message(phone, redirect_msg)
                return {
                    "current_node": "investor",
                    "tags": tags,
                    "kommo_contact_id": kommo_contact_id,
                    "kommo_lead_id": kommo_lead_id,
                    "last_question": last_question,
                    "awaiting_response": True,
                    "reask_count": reask_count + 1,
                }
            prioridades = "nao informado"

        tags = await _save_tag(lead_id, tags, "prioridades", prioridades)

        logger.info("INVESTOR | Prioridades=%r | phone=%s", prioridades, phone)

        # Classificar valores para o scoring
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
            "INVESTOR | Score=%d | Classificacao=%s | Categorias: "
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
                    score_type="investor",
                    investimento_pts=score_data["investimento_pts"],
                    pagamento_pts=score_data["pagamento_pts"],
                    urgencia_pts=score_data["urgencia_pts"],
                    situacao_pts=score_data["situacao_pts"],
                    dados_pts=score_data["dados_pts"],
                )

            # Atualizar classificacao do lead
            async with async_session() as session:
                lead_svc = LeadService(session)
                lead = await lead_svc.get_by_id(lead_id)
                if lead:
                    await lead_svc.update_classification(lead, classification, total_score)

        # Salvar classificação como tag para aparecer no CRM
        tags = await _save_tag(lead_id, tags, "classificacao_investidor", classification)

        # Sincronizar todas as tags coletadas com o KOMMO
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        # Atualizar stage no KOMMO conforme classificacao
        stage_id = kommo.stage_id_for_classification(classification)
        if stage_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        base_state = {
            "current_node": "investor",
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
            msg_opcoes = INVESTOR_QUENTE_OPCOES.format(
                nome=nome_display or "voce"
            )
            await send_whatsapp_message(phone, msg_opcoes)

            # Enviar imóveis compatíveis com o perfil do investidor
            async with async_session() as session:
                props_quente = await search_properties(
                    bairro=tags.get("localizacao", ""),
                    situacao=tags.get("situacao_imovel", ""),
                    investimento_categoria=investimento_categoria,
                    tipo=tags.get("lead_tipo_imovel", ""),
                    finalidade="Venda",
                    session=session,
                )
            imoveis_nomes: list[str] = []
            for prop in props_quente[:2]:
                await send_whatsapp_message(phone, format_property_whatsapp(prop))
                nome_prop = prop.get("empreendimento") or prop.get("tipo", "Imóvel")
                bairro_prop = prop.get("bairro", "")
                valor_prop = prop.get("valor", "")
                if bairro_prop:
                    nome_prop += f" — {bairro_prop}"
                if valor_prop:
                    from src.properties.formatter import _fmt_valor
                    nome_prop += f" ({_fmt_valor(valor_prop)})"
                imoveis_nomes.append(nome_prop)

            if imoveis_nomes:
                imoveis_str = " | ".join(imoveis_nomes)
            else:
                # Catálogo sem imóveis: descrever o perfil buscado para o corretor
                tipo_desc = tags.get("lead_tipo_imovel") or "Imóvel"
                regiao_desc = tags.get("localizacao", "")
                budget_desc = tags.get("faixa_valor", "")
                partes = [tipo_desc.capitalize()]
                if regiao_desc and not _is_off_topic(regiao_desc) and not _is_missing(regiao_desc):
                    partes[0] += f" em {regiao_desc}"
                if budget_desc and not _is_off_topic(budget_desc) and not _is_missing(budget_desc):
                    partes.append(budget_desc)
                if tags.get("situacao_imovel") and not _is_missing(tags["situacao_imovel"]):
                    partes.append(tags["situacao_imovel"].replace("_", " "))
                imoveis_str = " — ".join(partes) + " (sem imóveis no catálogo no momento)"

            tags = await _save_tag(lead_id, tags, "imoveis_apresentados", imoveis_str)
            logger.info(
                "INVESTOR | %d imóvel(is) enviado(s) ao lead QUENTE | imoveis=%r | phone=%s",
                len(props_quente[:2]),
                imoveis_str,
                phone,
            )

            # Agendar follow-up exclusivo de 10min (sem resposta).
            # Retornamos awaiting_response=False para o runner NAO agendar
            # timeout_5min automaticamente — o follow-up agendado abaixo
            # se encarrega de enviar 1 mensagem e so entao ativa o timeout generico.
            if lead_id:
                async with async_session() as session:
                    job_svc = JobService(session)
                    await job_svc.schedule_after(
                        lead_id,
                        "investor_quente_followup_10min",
                        timedelta(minutes=10),
                        payload={"phone": phone, "nome": nome_display or ""},
                    )
                logger.info(
                    "INVESTOR | Job investor_quente_followup_10min agendado "
                    "| phone=%s | lead_id=%s",
                    phone,
                    lead_id,
                )

            # Notificacao corretor URGENTE (SLA 2h) - TODO Feature 17: enviar WhatsApp
            if lead_id:
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
                            "tipo_imovel": tags.get("lead_tipo_imovel", ""),
                            "regiao": tags.get("localizacao", ""),
                            "budget": tags.get("faixa_valor", ""),
                            "pagamento": tags.get("forma_pagamento", ""),
                            "urgencia": tags.get("urgencia", ""),
                        },
                    )
                logger.info(
                    "INVESTOR | Notificacao corretor URGENTE (SLA 2h) criada "
                    "| phone=%s | score=%d",
                    phone,
                    total_score,
                )

            return {
                **base_state,
                # awaiting_response=False: o runner NAO agenda timeout_5min automatico.
                # O job investor_quente_followup_10min ja foi agendado acima.
                "awaiting_response": False,
                "last_question": "investor_quente_visita",
                "messages": [AIMessage(content=msg_opcoes)],
            }

        # ----------------------------------------------------------------
        # Branch MORNO (60-84 pts)
        # ----------------------------------------------------------------
        if classification == "morno":
            msg_selecao = INVESTOR_MORNO_SELECAO.format(nome=nome_display or "voce")
            await send_whatsapp_message(phone, msg_selecao)

            # Enviar seleção de imóveis compatíveis com o perfil
            async with async_session() as session:
                props_morno = await search_properties(
                    bairro=tags.get("localizacao", ""),
                    situacao=tags.get("situacao_imovel", ""),
                    investimento_categoria=investimento_categoria,
                    tipo=tags.get("lead_tipo_imovel", ""),
                    finalidade="Venda",
                    session=session,
                )
            for prop in props_morno[:2]:
                await send_whatsapp_message(phone, format_property_whatsapp(prop))
            logger.info(
                "INVESTOR | %d imóvel(is) enviado(s) ao lead MORNO | phone=%s",
                len(props_morno[:2]),
                phone,
            )

            # Notificacao corretor PADRAO (SLA 24h)
            if lead_id:
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
                            "tipo_imovel": tags.get("lead_tipo_imovel", ""),
                            "regiao": tags.get("localizacao", ""),
                            "pagamento": tags.get("forma_pagamento", ""),
                        },
                    )
                logger.info(
                    "INVESTOR | Notificacao corretor PADRAO (SLA 24h) criada "
                    "| phone=%s | score=%d",
                    phone,
                    total_score,
                )

            return {
                **base_state,
                "awaiting_response": True,
                "last_question": "investor_morno_contato",
                "messages": [AIMessage(content=msg_selecao)],
            }

        # ----------------------------------------------------------------
        # Branch FRIO (0-59 pts) — todos identificam barreira primeiro
        # ----------------------------------------------------------------

        # Setar stage CRM: Nutrição Ativa
        stage_nutricao = settings.kommo_stage_map_dict.get("nutricao_ativa")
        if stage_nutricao and kommo_lead_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_nutricao)

        # Todos os leads FRIO passam pelo router de barreira
        # (financeira / timing / conhecimento) independente do investimento.
        msg_barreira = INVESTOR_FRIO_BARREIRA.format(nome=nome_display or "voce")
        await send_whatsapp_message(phone, msg_barreira)

        # Agendar nutricao sequencial (1/7/15/30d) — handlers desativados ate conteudo ficar pronto
        if lead_id:
            async with async_session() as session:
                job_svc = JobService(session)
                for job_type, delay_days in [
                    ("investor_nurture_1d",  1),
                    ("investor_nurture_7d",  7),
                    ("investor_nurture_15d", 15),
                    ("investor_nurture_30d", 30),
                ]:
                    await job_svc.schedule_after(
                        lead_id=lead_id,
                        job_type=job_type,
                        delay=timedelta(days=delay_days),
                        payload={
                            "phone": phone,
                            "nome": nome_display or "",
                            "tipo_imovel": tags.get("lead_tipo_imovel", ""),
                            "regiao": tags.get("localizacao", ""),
                            "investimento": tags.get("faixa_valor", ""),
                        },
                    )
            logger.info(
                "INVESTOR | Nutricao investor 1/7/15/30d agendada (frio) | phone=%s | lead_id=%s",
                phone,
                lead_id,
            )

            async with async_session() as session:
                notif_svc = NotificationService(session)
                await notif_svc.create(
                    lead_id=lead_id,
                    notification_type="sistema",
                    sla_hours=None,
                    payload={
                        "phone": phone,
                        "score": total_score,
                        "nome": nome_display,
                        "estrategia": "nutricao_automatica_30_60_90d",
                    },
                )

        # Email disparado após identificar a barreira (em investor_frio_barreira)
        return {
            **base_state,
            "tags": tags,
            "awaiting_response": True,
            "last_question": "investor_frio_barreira",
            "messages": [AIMessage(content=msg_barreira)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a: Lead QUENTE - router de reacao (gostou / interessado / nao_gostou)
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_visita":
        reacao = await _classify_reacao_quente(effective_message)
        logger.info(
            "INVESTOR | Reacao quente=%s | phone=%s", reacao, phone
        )

        # -- Gostou: quer ver as opcoes, agendar visita --
        if reacao == "gostou":
            tags = await _save_tag(lead_id, tags, "visita_agendada", "true")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            stage_id = settings.kommo_stage_map_dict.get("oportunidade_quente")
            if stage_id and kommo_lead_id:
                await kommo.update_lead_stage(kommo_lead_id, stage_id)
            await send_whatsapp_message(phone, INVESTOR_QUENTE_ASK_VISITA)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_quente_data_visita",
                "reask_count": 0,
                "messages": [AIMessage(content=INVESTOR_QUENTE_ASK_VISITA)],
            }

        # -- Interessado: curioso, quer mais informacoes ou mais opcoes --
        if reacao == "interessado":
            tags = await _save_tag(lead_id, tags, "consultoria_agendada", "true")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            await send_whatsapp_message(phone, INVESTOR_QUENTE_MAIS_OPCOES)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_quente_mais_opcoes_resp",
                "reask_count": 0,
                "messages": [AIMessage(content=INVESTOR_QUENTE_MAIS_OPCOES)],
            }

        # -- Nao gostou: pede motivo para refinar a busca --
        tags = await _save_tag(lead_id, tags, "lead_nao_gostou", "true")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        await send_whatsapp_message(phone, INVESTOR_QUENTE_NAO_GOSTOU)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_quente_refinar",
            "messages": [AIMessage(content=INVESTOR_QUENTE_NAO_GOSTOU)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a-data: Captura data/horario da visita e encerra fluxo
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_data_visita":
        logger.info("INVESTOR | Capturando data da visita | phone=%s", phone)

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
                "INVESTOR | Data vaga (%s) -> perguntando qual das 3 proximas | phone=%s",
                vague_day, phone,
            )
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_quente_data_visita_confirm",
                "messages": [AIMessage(content=msg)],
            }

        data_visita = await _extract_field(
            effective_message, "data e horario da visita informados pelo lead"
        )
        if data_visita and not _is_off_topic(data_visita) and not _is_missing(data_visita):
            tags = await _save_tag(lead_id, tags, "data_visita", data_visita)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        logger.info("INVESTOR | Data visita=%r | phone=%s", data_visita, phone)

        await send_whatsapp_message(phone, INVESTOR_QUENTE_VISITA_CONFIRMADA)
        await _notify_corretor_visita(phone, tags, total_score)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=INVESTOR_QUENTE_VISITA_CONFIRMADA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a-data-confirm: Lead confirmou data especifica da visita
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_data_visita_confirm":
        logger.info("INVESTOR | Confirmando data especifica da visita | phone=%s", phone)

        data_visita = await _extract_field(
            effective_message, "data e horario da visita informados pelo lead"
        )
        if data_visita and not _is_off_topic(data_visita) and not _is_missing(data_visita):
            tags = await _save_tag(lead_id, tags, "data_visita", data_visita)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        logger.info("INVESTOR | Data visita confirmada=%r | phone=%s", data_visita, phone)

        await send_whatsapp_message(phone, INVESTOR_QUENTE_VISITA_CONFIRMADA)
        await _notify_corretor_visita(phone, tags, total_score)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=INVESTOR_QUENTE_VISITA_CONFIRMADA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a-mais-opcoes: Lead interessado respondeu data/confirmacao
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_mais_opcoes_resp":
        logger.info("INVESTOR | Encerrando fluxo quente (interessado) | phone=%s", phone)

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
                "INVESTOR | Data vaga (%s) -> perguntando qual das 3 proximas | phone=%s",
                vague_day, phone,
            )
            await send_whatsapp_message(phone, msg)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_quente_mais_opcoes_data_confirm",
                "messages": [AIMessage(content=msg)],
            }

        data_visita = await _extract_field(
            effective_message, "data e horario da visita informados pelo lead"
        )
        if data_visita and not _is_off_topic(data_visita) and not _is_missing(data_visita):
            tags = await _save_tag(lead_id, tags, "data_visita", data_visita)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg_enc = (
            "Nosso consultor já recebeu suas informações e vai entrar em contato "
            "para confirmar tudo. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_enc)
        await _notify_corretor_visita(phone, tags, total_score)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a-mais-opcoes-data-confirm: Confirmacao da data especifica
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_mais_opcoes_data_confirm":
        logger.info("INVESTOR | Confirmando data especifica (mais opcoes) | phone=%s", phone)

        data_visita = await _extract_field(
            effective_message, "data e horario da visita informados pelo lead"
        )
        if data_visita and not _is_off_topic(data_visita) and not _is_missing(data_visita):
            tags = await _save_tag(lead_id, tags, "data_visita", data_visita)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg_enc = (
            "Nosso consultor já recebeu suas informações e vai entrar em contato "
            "para confirmar tudo. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_enc)
        await _notify_corretor_visita(phone, tags, total_score)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7a-refinar: Lead nao gostou - processa motivo e volta ao router
    # -----------------------------------------------------------------------
    if last_question == "investor_quente_refinar":
        logger.info(
            "INVESTOR | Capturando barreira e refinando busca | phone=%s", phone
        )

        barreira = await _extract_field(
            effective_message,
            "motivo pelo qual o lead nao gostou das opcoes (preco, localizacao, tamanho, acabamento, outro)",
        )
        tags = await _save_tag(lead_id, tags, "barreira_busca", barreira)

        logger.info("INVESTOR | Barreira=%r | phone=%s", barreira, phone)

        nome_exibir = lead_name or tags.get("lead_identificado", "")
        msg = INVESTOR_QUENTE_NOVAS_OPCOES.format(nome=nome_exibir or "")
        await send_whatsapp_message(phone, msg)

        # Agenda novo follow-up de 10min e volta ao router de reacao
        if lead_id:
            async with async_session() as session:
                job_svc = JobService(session)
                await job_svc.schedule_after(
                    lead_id,
                    "investor_quente_followup_10min",
                    timedelta(minutes=10),
                    payload={"phone": phone, "nome": nome_exibir or ""},
                )

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": "investor_quente_visita",  # volta ao router de reacao
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7b: Lead MORNO - classificar preferencia de contato (email vs whatsapp)
    # -----------------------------------------------------------------------
    if last_question == "investor_morno_contato":
        logger.info(
            "INVESTOR | Classificando preferencia de contato (morno) | phone=%s", phone
        )

        tipo_contato = await _classify_field(
            _CLASSIFY_CONTATO_TIPO_PROMPT, effective_message
        )
        logger.info(
            "INVESTOR | Tipo contato=%r | phone=%s", tipo_contato, phone
        )

        if tipo_contato == "email":
            await send_whatsapp_message(phone, INVESTOR_MORNO_ASK_EMAIL)
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_morno_email",
                "messages": [AIMessage(content=INVESTOR_MORNO_ASK_EMAIL)],
            }

        # whatsapp ou indefinido -> perguntar se e o mesmo numero
        await send_whatsapp_message(phone, INVESTOR_MORNO_ASK_WHATS)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_morno_whats",
            "messages": [AIMessage(content=INVESTOR_MORNO_ASK_WHATS)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7c: Lead MORNO - capturou email
    # -----------------------------------------------------------------------
    if last_question == "investor_morno_email":
        logger.info(
            "INVESTOR | Capturando email (morno) | phone=%s", phone
        )

        email = await _extract_field(effective_message, "endereco de e-mail")
        if email and email != "nao informado":
            tags = await _save_tag(lead_id, tags, "email_lead", email)
            tags = await _save_tag(lead_id, tags, "contato_adicional", email)

        tags = await _save_tag(lead_id, tags, "contato_coletado", "true")
        logger.info("INVESTOR | Email=%r | phone=%s", email, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        stage_id = settings.kommo_stage_map_dict.get("follow_up_programado")
        if stage_id and kommo_lead_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        await _notify_corretor_morno(phone, tags, total_score)
        await send_whatsapp_message(phone, INVESTOR_MORNO_CONSULTORIA)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_morno_consultoria_resp",
            "reask_count": 0,
            "messages": [AIMessage(content=INVESTOR_MORNO_CONSULTORIA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7d: Lead MORNO - capturou whatsapp (mesmo numero ou outro)
    # -----------------------------------------------------------------------
    if last_question == "investor_morno_whats":
        logger.info(
            "INVESTOR | Capturando WhatsApp (morno) | phone=%s", phone
        )

        # Verificar se informou outro numero ou confirmou o atual
        outro_numero = await _extract_field(
            effective_message, "numero de WhatsApp (apenas se for diferente do atual)"
        )
        contato_whats = (
            outro_numero
            if outro_numero and outro_numero != "nao informado"
            else phone
        )
        tags = await _save_tag(lead_id, tags, "contato_adicional", contato_whats)
        tags = await _save_tag(lead_id, tags, "contato_coletado", "true")

        logger.info("INVESTOR | WhatsApp=%r | phone=%s", contato_whats, phone)

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        stage_id = settings.kommo_stage_map_dict.get("follow_up_programado")
        if stage_id and kommo_lead_id:
            await kommo.update_lead_stage(kommo_lead_id, stage_id)

        await _notify_corretor_morno(phone, tags, total_score)
        await send_whatsapp_message(phone, INVESTOR_MORNO_CONSULTORIA)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_morno_consultoria_resp",
            "reask_count": 0,
            "messages": [AIMessage(content=INVESTOR_MORNO_CONSULTORIA)],
        }

    # -----------------------------------------------------------------------
    # Etapa 7e: Lead MORNO - resposta da consultoria → encerrar fluxo
    # -----------------------------------------------------------------------
    if last_question == "investor_morno_consultoria_resp":
        logger.info("INVESTOR | Encerrando fluxo morno | phone=%s", phone)

        tags = await _save_tag(lead_id, tags, "consultoria_agendada", "true")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        msg_encerramento = (
            "Nosso consultor já recebeu suas informações e vai entrar em contato "
            "para confirmar tudo. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_encerramento)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=msg_encerramento)],
        }

    # -----------------------------------------------------------------------
    # Etapa 8-parceiro: Lead recebeu contato do parceiro → encerra com nutricao
    # -----------------------------------------------------------------------
    if last_question == "investor_frio_parceiro_resp":
        logger.info("INVESTOR | Enviando contato do parceiro (frio) | phone=%s", phone)
        await send_whatsapp_message(phone, INVESTOR_FRIO_CONTATO_PARCEIRO)
        await send_whatsapp_message(phone, INVESTOR_FRIO_NUTRICAO)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [
                AIMessage(content=INVESTOR_FRIO_CONTATO_PARCEIRO),
                AIMessage(content=INVESTOR_FRIO_NUTRICAO),
            ],
        }

    # -----------------------------------------------------------------------
    # Etapa 8a: Lead FRIO - router de barreira (financeira / timing / conhecimento)
    # -----------------------------------------------------------------------
    if last_question == "investor_frio_barreira":
        logger.info(
            "INVESTOR | Classificando barreira (frio) | phone=%s", phone
        )

        barreira = await _classify_barreira_frio(effective_message)
        tags = await _save_tag(lead_id, tags, "barreira_frio", barreira)
        logger.info(
            "INVESTOR | Barreira frio=%r | phone=%s", barreira, phone
        )

        nome_exibir = lead_name or tags.get("lead_identificado", "")

        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)

        if barreira == "financeira":
            tags = await _save_tag(lead_id, tags, "consultoria_agendada", "true")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            msg = INVESTOR_FRIO_FINANCEIRA.format(nome=nome_exibir or "voce")
            await send_whatsapp_message(phone, msg)
            await _notify_corretor_frio(
                phone, tags, total_score,
                barreira="Financeira",
                estrategia="Consultor financeiro apresentado",
            )
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_frio_encerramento",
                "messages": [AIMessage(content=msg)],
            }

        if barreira == "timing":
            tags = await _save_tag(lead_id, tags, "lista_vip", "true")
            await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
            msg = INVESTOR_FRIO_TIMING.format(nome=nome_exibir or "voce")
            await send_whatsapp_message(phone, msg)
            await _notify_corretor_frio(
                phone, tags, total_score,
                barreira="Timing",
                estrategia="Lista VIP ativada + guia do mercado enviado",
            )
            return {
                "current_node": "investor",
                "tags": tags,
                "kommo_contact_id": kommo_contact_id,
                "kommo_lead_id": kommo_lead_id,
                "awaiting_response": True,
                "last_question": "investor_frio_encerramento",
                "messages": [AIMessage(content=msg)],
            }

        # conhecimento (fallback)
        tags = await _save_tag(lead_id, tags, "tour_agendado", "true")
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg = INVESTOR_FRIO_CONHECIMENTO.format(nome=nome_exibir or "voce")
        await send_whatsapp_message(phone, msg)
        await _notify_corretor_frio(
            phone, tags, total_score,
            barreira="Conhecimento",
            estrategia="Tour no showroom proposto",
        )
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": True,
            "last_question": "investor_frio_conhecimento_resp",
            "reask_count": 0,
            "messages": [AIMessage(content=msg)],
        }

    # -----------------------------------------------------------------------
    # Etapa 8a-encerramento: Lead frio (financeira/timing) confirmou interesse
    # -----------------------------------------------------------------------
    if last_question == "investor_frio_encerramento":
        logger.info("INVESTOR | Encerrando fluxo frio (financeira/timing) | phone=%s", phone)
        await kommo.sync_tags(kommo_lead_id, kommo_contact_id, tags)
        msg_enc = (
            "Ótimo! Nosso consultor já recebeu suas informações e vai entrar em contato "
            "em breve para dar continuidade. Até logo! 😊"
        )
        await send_whatsapp_message(phone, msg_enc)
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Etapa 8a-conhecimento: Lead frio conhecimento respondeu data do tour
    # -----------------------------------------------------------------------
    if last_question == "investor_frio_conhecimento_resp":
        logger.info("INVESTOR | Encerrando fluxo frio (conhecimento) | phone=%s", phone)

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
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
            "messages": [AIMessage(content=msg_enc)],
        }

    # -----------------------------------------------------------------------
    # Fallback: estado desconhecido - reiniciar fluxo
    # -----------------------------------------------------------------------

    # last_question=None significa que a conversa já foi concluída.
    # O lead enviou uma mensagem de cortesia depois do encerramento — ignorar.
    if last_question is None:
        logger.info(
            "INVESTOR | Mensagem recebida apos conclusao do fluxo — ignorando | phone=%s", phone
        )
        return {
            "current_node": "investor",
            "tags": tags,
            "kommo_contact_id": kommo_contact_id,
            "kommo_lead_id": kommo_lead_id,
            "awaiting_response": False,
            "last_question": None,
        }

    logger.warning(
        "INVESTOR | Estado desconhecido last_question=%r | phone=%s",
        last_question,
        phone,
    )
    await send_whatsapp_message(phone, INVESTOR_INITIAL)
    return {
        "current_node": "investor",
        "kommo_contact_id": kommo_contact_id,
        "kommo_lead_id": kommo_lead_id,
        "awaiting_response": True,
        "last_question": "investor_estrategia",
        "messages": [AIMessage(content=INVESTOR_INITIAL)],
    }
