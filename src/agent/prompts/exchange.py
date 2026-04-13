"""
Prompts do fluxo de permuta (Feature 13).

Etapas:
  1. EXCHANGE_INITIAL           -> apresenta permuta, pede localização + tipo + nome
  2. EXCHANGE_ASK_DETALHES      -> pede suítes + estado de conservação
  3. EXCHANGE_AGENDAMENTO       -> informa avaliação dupla, pede contato preferencial
  4a. EXCHANGE_CONFIRM_CONTATO  -> confirma agendamento com contato recebido
  4b. EXCHANGE_SEM_CONTATO      -> confirma contato pelo próprio número
"""

# ---------------------------------------------------------------------------
# Etapa 1 - Abertura
# ---------------------------------------------------------------------------

EXCHANGE_INITIAL = (
    "Que interessante! Permuta pode ser uma ótima estratégia 📝 😊\n\n"
    "Me conta sobre o imóvel que você tem hoje:\n"
    "Onde fica? Qual o tipo e tamanho?\n"
    "Quantas suítes? Qual o estado?"
)

# ---------------------------------------------------------------------------
# Etapa 2 - Suites + Conservacao
# ---------------------------------------------------------------------------

EXCHANGE_ASK_DETALHES = (
    "{nome}, para nossa equipe preparar a avaliação correta...\n\n"
    "Quantas *suítes* tem o imóvel?\n\n"
    "E qual é o *estado de conservação*? "
    "(Novo, ótimo, bom, precisa de reformas...)"
)

# ---------------------------------------------------------------------------
# Etapa 3 - Avaliacao dupla + pedido de contato
# ---------------------------------------------------------------------------

EXCHANGE_AGENDAMENTO = (
    "{nome}, tenho todas as informações necessárias.\n\n"
    "Com esse perfil, nosso especialista vai preparar uma *Avaliação Dupla*:\n\n"
    "1. Avaliação detalhada e valoração do seu imóvel atual\n"
    "2. Seleção das melhores opções de permuta disponíveis em nosso portfólio\n\n"
    "Para confirmarmos o agendamento, você tem algum contato preferencial? "
    "(E-mail ou outro WhatsApp)"
)

# ---------------------------------------------------------------------------
# Etapa 4 - Confirmacoes
# ---------------------------------------------------------------------------

EXCHANGE_CONFIRM_CONTATO = (
    "Nosso especialista em permuta vai entrar em contato em até 24 horas "
    "para agendar a Avaliação Dupla presencial.\n\n"
    "Qualquer dúvida, estou por aqui. Até logo, {nome}!"
)

EXCHANGE_SEM_CONTATO = (
    "Entendido! Nosso especialista vai entrar em contato diretamente "
    "por este número em até 24 horas para agendar a Avaliação Dupla.\n\n"
    "Qualquer dúvida, estou por aqui. Até logo, {nome}!"
)
