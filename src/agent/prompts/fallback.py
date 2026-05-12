"""
fallback.py - Mensagens de fallback e utilitários de redirecionamento de fluxo.

Centraliza:
  - Mensagem de erro técnico (enviada quando o agente crasha)
  - Mapeamento de last_question → descrição humana do tópico pendente
  - Função para gerar mensagem dinâmica de redirecionamento ao fluxo
  - is_clarification(): detecta pedidos de esclarecimento da pergunta atual
  - is_faq_question(): detecção rápida via regex
  - is_faq_question_async(): detecção robusta — regex + fallback LLM
"""

import re

# ---------------------------------------------------------------------------
# Detecção de pedido de esclarecimento (sem LLM — rápido e sem custo)
# ---------------------------------------------------------------------------

# Regex de clarificação: a mensagem deve COMEÇAR com um dos padrões abaixo,
# mas pode ter conteúdo extra depois (comum em áudios transcritos, ex:
# "Não entendi o que você quis dizer com isso" ainda é uma clarificação).
_CLARIFICATION_RE = re.compile(
    r"^(como assim|o que quer dizer|o que significa|o que [eé] isso|o que seria isso|"
    r"n[aã]o entendi|n[aã]o entendo|n[aã]o t[oô] entendendo|n[aã]o entendi nada|n[aã]o t[oô] entendendo nada|"
    r"pode (me )?explicar|me explica(r)?|me explique|explica melhor|me explica mais|"
    r"voc[eê] pode me explicar|voc[eê] (me )?explica(r)?|"
    r"n[aã]o compreendi|pode repetir|pode esclarecer|me esclarece(r)?|"
    r"o que isso|que isso|"
    r"n[aã]o ficou claro|ficou confuso|"
    r"t[oô] confuso|estou confus[ao]|"
    r"n[aã]o t[oô] acompanhando|n[aã]o acompanhei|"
    r"n[aã]o (fui |consegui )?(entender|compreender)|"
    r"fiquei confus[ao]|que pergunta [eé] essa|que [eé] essa pergunta)",
    re.IGNORECASE,
)

# Remove endereços de e-mail da mensagem antes de checar FAQ.
# Evita falsos positivos quando o domínio do e-mail contém palavras da empresa
# (ex: "gustavo@residere.com.br" não é uma pergunta sobre a imobiliária).
_EMAIL_PATTERN = re.compile(r"[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)


def _strip_emails(message: str) -> str:
    """Remove endereços de e-mail da mensagem antes de aplicar detecção de FAQ."""
    return _EMAIL_PATTERN.sub("", message).strip()


# Detecta perguntas sobre a empresa ou processos imobiliários que devem ir para o FAQ.
# Diferente das clarificações genéricas, aqui o lead menciona algo específico.
_FAQ_RE = re.compile(
    r"(casa andreia|andreia perez|residere|a imobili[aá]ria|"
    r"endere[cç]o|onde fica[ms]?|onde voc[eê]s (ficam|est[aã]o)|"
    r"\bcnpj\b|\bcreci\b|credenciado|"
    r"como funciona (o |a )?(financiamento|processo|cadastro|compra|venda|avalia[çc][aã]o)|"
    r"quais? (s[aã]o os? )?documentos|"
    r"o que [eé] (a |o )?(imobili[aá]ria|residere|andreia|casa andreia)|"
    r"voc[eê]s? (s[aã]o|[eé]) (uma? )?imobili[aá]ria|"
    # Horário e atendimento
    r"hor[aá]rio (de )?(atendimento|funcionamento|trabalho)|"
    r"que horas (voc[eê]s )?abr[em]|que horas (voc[eê]s )?fech[am]|"
    r"quando voc[eê]s atendem|atendem (no )?(s[aá]bado|domingo|fim de semana|feriado)|"
    r"voc[eê]s atendem aos (s[aá]bados|domingos)|"
    # Contato e canais
    r"\btelefone\b|\bwhatsapp\b|\bsite\b|\binstagram\b|\bfacebook\b|\bemail\b|"
    r"como (eu )?entro em contato|como falo com voc[eê]s|"
    # Equipe e atendimento humano
    r"falar com (um |o |a )?corretor|falar com algu[eé]m|"
    r"atendimento humano|falar com uma? pessoa|"
    r"tem algu[eé]m (para|pra) (me )?(atender|ajudar)|"
    # Financeiro / comissão
    r"comiss[aã]o|taxa de corretagem|taxa de administra[çc][aã]o|"
    r"quanto (voc[eê]s )?cobram|qual [eé] o (valor|pre[çc]o) (da|do) (taxa|comiss[aã]o)|"
    # Processo e prazo
    r"quanto tempo (leva|demora)|prazo (de|para) (avalia[çc][aã]o|venda|loca[çc][aã]o|processo)|"
    r"o que (eu )?preciso (para|trazer|levar)|quais (s[aã]o os )?requisitos|"
    # Cobertura / região de atuação
    r"\batendem\s+(em|n[ao]s?)\b|"
    r"voc[eê]s? (tamb[eé]m )?(atendem|atuam|trabalham)\b|"
    r"\batuam\s+(em|n[ao]s?)\b|"
    r"[aá]rea (de )?atendimento|regi[oõ]es? (de )?(atendimento|atua[çc][aã]o)|"
    r"cobrem (a |o |essa |esta )?regi[aã]o|qual [eé] a regi[aã]o (de voc[eê]s|de atua[çc][aã]o)|"
    r"onde voc[eê]s? (atuam|trabalham|operam)|"
    # Disponibilidade de imóveis
    r"voc[eê]s? (t[eê]m|tem|possu[ií]) im[oó]ve[il]s?|"
    r"t[eê]m (im[oó]veis?|ap[aê]s?|casas?|terrenos?) (disponíveis?|para (venda|aluguel|loca[çc][aã]o))"
    r")",
    re.IGNORECASE,
)


def is_clarification(message: str) -> bool:
    """
    Retorna True se a mensagem é um pedido de esclarecimento da pergunta atual do fluxo.
    Exemplos: 'Como assim?', 'Não entendi', 'Pode explicar?', 'Você pode me explicar isso?'
    Usa somente regex (sem LLM).
    """
    return bool(_CLARIFICATION_RE.match(message.strip()))


def is_faq_question(message: str) -> bool:
    """
    Retorna True se a mensagem é uma pergunta sobre a empresa ou processos imobiliários
    que deve ser respondida pelo FAQ, independente do fluxo ativo.
    Exemplos: 'O que é a Casa Andreia Perez?', 'Qual o endereço de vocês?', 'Qual o CNPJ?'
    Diferente de is_clarification(): aqui o lead pergunta sobre algo específico externo ao fluxo.
    Usa somente regex (sem LLM) — rápido e sem custo.

    E-mails são removidos antes da verificação para evitar falsos positivos quando o
    domínio do e-mail contém palavras-chave da empresa (ex: "joao@residere.com.br").
    """
    clean = _strip_emails(message)
    if not clean:
        return False
    return bool(_FAQ_RE.search(clean))


# Indicadores rápidos de que a mensagem pode ser uma pergunta (pré-filtro antes do LLM)
_QUESTION_HINT_RE = re.compile(
    r"\?|^(o que|qual|como|onde|quando|por que|quanto|quem|voc[eê]s?|"
    r"atendem|atuam|trabalham|cobrem|existe|tem |h[aá] )",
    re.IGNORECASE,
)

# Prompt para o LLM classificar se é uma pergunta FAQ
_FAQ_LLM_PROMPT = """Você é um classificador de mensagens para um chatbot imobiliário.

Analise a mensagem abaixo e responda APENAS com "sim" ou "não":

A mensagem é uma pergunta ou dúvida sobre a empresa imobiliária, seus serviços, área de atuação, regiões atendidas, processos, taxas, comissões, horários, contatos, documentos ou qualquer informação geral sobre a empresa?

Responda "sim" se a mensagem:
- Pergunta sobre a empresa, imobiliária ou seus serviços
- Pergunta sobre localização, cidades ou regiões onde a empresa atua
- Pergunta sobre como funciona algum processo (financiamento, documentação, avaliação etc.)
- Pergunta sobre taxas, comissões ou valores cobrados pela empresa
- Pergunta sobre horários de atendimento ou formas de contato

Responda "não" se a mensagem:
- É uma resposta direta (ex: "sim", "não", "Cuiabá", "R$ 500.000", "3 quartos")
- Expressa interesse em comprar, vender, investir ou alugar um imóvel
- É um cumprimento, agradecimento ou mensagem genérica sem pergunta sobre a empresa

Mensagem: {message}

Resposta (apenas "sim" ou "não"):"""


async def is_faq_question_async(message: str) -> bool:
    """
    Versão robusta: regex primeiro (rápido/grátis) e, se não casar,
    usa LLM como fallback para capturar perguntas que a regex não cobre.

    O LLM só é chamado se a mensagem contiver indicadores de pergunta,
    evitando chamadas desnecessárias em respostas curtas como 'sim' ou '500000'.
    """
    # 1. Fast path: regex
    if is_faq_question(message):
        return True

    # 2. Pré-filtro: só aciona LLM se a mensagem parecer uma pergunta
    if not _QUESTION_HINT_RE.search(message.strip()):
        return False

    # 3. LLM fallback
    try:
        from langchain_openai import ChatOpenAI
        from src.config.settings import settings
        from src.utils.logger import logger as _logger

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            api_key=settings.openai_api_key,
            timeout=10,
        )
        prompt = _FAQ_LLM_PROMPT.format(message=message[:500])
        response = await llm.ainvoke(prompt)
        answer = (response.content or "").strip().lower()
        is_faq = answer.startswith("sim")
        _logger.debug("FAQ_DETECT | LLM | msg=%r | resultado=%s", message[:60], is_faq)
        return is_faq
    except Exception as exc:
        from src.utils.logger import logger as _logger
        _logger.warning("FAQ_DETECT | LLM falhou, usando apenas regex | erro=%s", str(exc))
        return False


# ---------------------------------------------------------------------------
# Mensagem de erro técnico genérico
# ---------------------------------------------------------------------------

TECHNICAL_ERROR_MESSAGE = (
    "Opa, tive um probleminha técnico aqui! 😅 "
    "Pode repetir sua mensagem? Já resolvo isso pra você!"
)

# ---------------------------------------------------------------------------
# Mapeamento: last_question → descrição amigável do que estava sendo perguntado
# ---------------------------------------------------------------------------

LAST_QUESTION_LABELS: dict[str, str] = {
    # Fluxo de venda
    "sale_regiao": "a região onde fica o seu imóvel",
    "sale_estilo": "o estilo do imóvel (casa, apartamento, cobertura...)",
    "sale_suites": "as suítes e diferenciais do imóvel",
    "sale_perguntas_finais": "o valor esperado, prazo e exclusividade",
    "sale_visita": "o agendamento da visita técnica",
    # Fluxo de locação
    "rental_dados": "o tipo e localização do imóvel para locação",
    "rental_perguntas": "detalhes sobre o imóvel (valor, ocupação, reforma)",
    "rental_email": "o seu e-mail para envio da proposta",
    # Fluxo de investidor
    "investor_estrategia": "sua estratégia de investimento (renda ou valorização)",
    "investor_tipo": "o tipo de imóvel que você busca",
    "investor_tipo_nome": "o tipo e nome do empreendimento",
    "investor_nome": "o seu nome",
    "investor_regiao": "a região de interesse",
    "investor_investimento": "a faixa de investimento",
    "investor_necessidades": "as características do imóvel (suítes, diferenciais)",
    "investor_garagem": "a necessidade de vagas de garagem",
    "investor_situacao": "sua preferência entre imóvel pronto ou lançamento",
    "investor_pagamento": "a forma de pagamento",
    "investor_urgencia": "o prazo para sua decisão",
    "investor_prioridades": "suas principais prioridades na compra",
    "investor_quente_visita": "o agendamento da visita exclusiva",
    "investor_morno_contato": "sua preferência de contato (WhatsApp ou e-mail)",
    "investor_frio_barreira": "o que te impede de avançar agora",
    # Fluxo de permuta
    "exchange_dados": "as informações do seu imóvel atual para permuta",
    "exchange_detalhes": "as suítes e estado de conservação do imóvel",
    "exchange_contato": "seu contato preferencial para agendamento",
    # Fluxo de interesse específico
    "specific_interesse": "se você viu um anúncio específico nosso",
    "specific_empreendimento": "o nome do empreendimento que te interessou",
    # Fluxo de comprador
    "buyer_tipo_ask": "sua preferência entre imóvel pronto para morar ou um lançamento (na planta)",
    "buyer_ticket": "a faixa de investimento que você considera",
    "buyer_tipo": "sua preferência entre imóvel pronto ou lançamento",
    "buyer_barreira": "o que te impede de avançar no momento",
    "buyer_pronto_nome": "o seu nome",
    "buyer_pronto_faixa": "a faixa de valor que você considera para o imóvel",
    "buyer_pronto_pagamento": "a forma de pagamento preferida (à vista, financiamento, etc)",
    "buyer_pronto_urgencia": "o prazo ou urgência para fechar o negócio",
    "buyer_pronto_prioridades": "suas principais prioridades no imóvel (segurança, lazer, localização...)",
    "buyer_pronto_preferencias": "a região e quantidade de suítes preferidas",
    "buyer_pronto_visita": "se você quer agendar uma visita ao imóvel",
    "buyer_pronto_data": "a data e horário para a visita",
    "buyer_pronto_data_confirm": "a data preferida para a visita",
    "buyer_pronto_horario": "o horário preferido para a visita",
    "buyer_pronto_barreira": "o que está te impedindo de avançar agora",
    # Fluxo de lançamento
    "launch_nome": "o seu nome",
    "launch_regiao_conhece": "se você conhece a região do empreendimento",
    "launch_pagamento": "a forma de pagamento preferida",
    "launch_urgencia": "o prazo para sua decisão",
    "launch_quente_visita": "o agendamento da apresentação exclusiva",
    # Fluxo genérico
    "generic_explanation": "o que você está buscando (comprar, vender ou investir)",
    "generic_re_clarify": "se você quer comprar/investir ou vender/alugar um imóvel",
}


def get_pending_topic(last_question: str | None) -> str:
    """
    Retorna descrição amigável do tópico que estava sendo perguntado.

    Usado para:
    - Mensagem de redirecionamento quando lead vai off-topic em um fluxo
    - Confirmação do FAQ quando há fluxo ativo
    """
    if not last_question:
        return "o que você precisa"
    return LAST_QUESTION_LABELS.get(last_question, "sua resposta anterior")


def build_redirect_message(last_question: str | None) -> str:
    """
    Constrói mensagem de redirecionamento ao fluxo quando lead vai off-topic.

    Exemplo: "Entendi! Para eu poder te ajudar da melhor forma,
              preciso que você me responda: a região onde fica o seu imóvel. 😊"
    """
    topic = get_pending_topic(last_question)
    return (
        f"Entendi! Para eu poder te ajudar da melhor forma, "
        f"preciso que você me responda: *{topic}*. 😊"
    )


# ---------------------------------------------------------------------------
# Off-topic inteligente: responde a pergunta + redireciona ao fluxo
# ---------------------------------------------------------------------------

from langchain_core.messages import AIMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from src.config.settings import settings  # noqa: E402

# Prompt usado quando temos o texto exato da última mensagem do agente.
# O LLM analisa o contexto real e explica a pergunta ao lead.
_OFFTOPIC_PROMPT_WITH_CONTEXT = """Você é a Andreia, assistente da Residere (imobiliária de alto padrão em Cuiabá-MT).

Estamos em uma conversa de qualificação imobiliária. O agente acabou de fazer esta pergunta ao lead:
"{last_bot_message}"

O lead respondeu:
"{lead_message}"

Se o lead pediu esclarecimento ('Como assim?', 'Não entendi'), explique o que essa pergunta significa de forma simples e natural — diga por que precisamos dessa informação para ajudá-lo a encontrar o imóvel ideal. Depois, faça a pergunta novamente com outras palavras.
Se foi off-topic (comentário fora do assunto), responda brevemente em 1-2 frases e volte para a pergunta.

IMPORTANTE:
- Não inicie com saudações como "Oi!", "Olá!", "Bom dia!" — a conversa já está em andamento.
- Responda em português brasileiro, tom informal, até 3 linhas.
- Não use markdown nem asteriscos."""

# Prompt de fallback usado quando não temos o texto da última mensagem.
_OFFTOPIC_PROMPT_FALLBACK = """Você é a Andreia, assistente da Residere (imobiliária de alto padrão em Cuiabá-MT).

O lead está em um fluxo de qualificação e pediu esclarecimento ou foi off-topic. O tópico pendente é: {pending_topic}

Mensagem do lead: {lead_message}

Responda brevemente (1-2 frases) e volte para a pergunta pendente.

IMPORTANTE:
- Não inicie com saudações como "Oi!", "Olá!", "Bom dia!" — a conversa já está em andamento.
- Responda em português brasileiro, tom informal, até 3 linhas.
- Não use markdown nem asteriscos."""


def get_last_bot_message(messages: list) -> str | None:
    """Extrai o texto da última mensagem enviada pelo agente a partir do histórico."""
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content).strip()
    return None


async def build_smart_redirect(
    lead_message: str,
    last_question: str | None,
    last_bot_message: str | None = None,
) -> str:
    """
    Gera resposta que: (a) explica/responde o lead, (b) redireciona ao fluxo.

    Quando last_bot_message é fornecido, o LLM usa o texto real da última
    pergunta feita para explicar o contexto ao lead.
    Fallback: se o LLM falhar, retorna a mensagem simples de build_redirect_message.
    """
    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.3,
            api_key=settings.openai_api_key,
            timeout=15,
        )
        if last_bot_message:
            prompt = _OFFTOPIC_PROMPT_WITH_CONTEXT.format(
                last_bot_message=last_bot_message[:500],
                lead_message=lead_message[:500],
            )
        else:
            pending = get_pending_topic(last_question)
            prompt = _OFFTOPIC_PROMPT_FALLBACK.format(
                lead_message=lead_message[:500],
                pending_topic=pending,
            )
        response = await llm.ainvoke(prompt)
        text = (response.content or "").strip()
        if text:
            return text
    except Exception as exc:
        from src.utils.logger import logger
        logger.warning("OFFTOPIC | LLM falhou, usando fallback seco | erro=%s", str(exc))

    return build_redirect_message(last_question)


# ---------------------------------------------------------------------------
# Timeout inteligente: retoma a conversa de onde parou
# ---------------------------------------------------------------------------

_TIMEOUT_SMART_PROMPT = """Você é a Andreia, assistente da Residere (imobiliária de alto padrão em Cuiabá-MT).

Você estava qualificando um lead que parou de responder. Precisa retomar a conversa de onde parou.

Nome do lead: {lead_name}
Última pergunta feita ao lead: {last_bot_message}
Assunto pendente: {pending_topic}

Escreva uma mensagem curta e natural para retomar a conversa. A mensagem deve:
- Referenciar o assunto que estava sendo tratado (não seja genérico)
- Relançar a pergunta pendente de forma suave, com outras palavras se possível
- Ser acolhedora e sem pressão

IMPORTANTE:
- Não diga frases como "quando quiser voltar é só me chamar" — queremos continuar agora
- Não inicie com saudações isoladas como "Oi!" — vá direto ao ponto
- Responda em português brasileiro, tom informal
- Máximo 3 linhas, sem markdown nem asteriscos"""


async def build_smart_timeout_message(
    lead_name: str,
    last_question: str | None,
    last_bot_message: str | None,
) -> str:
    """
    Gera mensagem de follow-up contextual para reengajar lead inativo.

    Usa o histórico da última pergunta feita para retomar de onde parou,
    em vez de enviar uma mensagem genérica fixa.
    Fallback: mensagem simples baseada no tópico pendente.
    """
    name_display = lead_name or "você"
    pending = get_pending_topic(last_question)
    last_msg = last_bot_message or f"sua resposta sobre {pending}"

    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.4,
            api_key=settings.openai_api_key,
            timeout=15,
        )
        prompt = _TIMEOUT_SMART_PROMPT.format(
            lead_name=name_display,
            last_bot_message=last_msg[:400],
            pending_topic=pending,
        )
        response = await llm.ainvoke(prompt)
        text = (response.content or "").strip()
        if text:
            return text
    except Exception as exc:
        from src.utils.logger import logger
        logger.warning("TIMEOUT_SMART | LLM falhou, usando fallback | erro=%s", str(exc))

    return f"{name_display}, ainda está por aqui? Precisava da sua resposta sobre {pending}."
