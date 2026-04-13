"""
Prompts do fluxo de investidor (Feature 12).

Etapas:
  1. INVESTOR_INITIAL          -> pergunta estratégia (renda aluguel ou revenda?)
  2. INVESTOR_ASK_TIPO_NOME    -> pergunta tipo de imóvel + nome (pausa natural)
  3. INVESTOR_ASK_REGIAO       -> pergunta região + faixa de investimento
  4. INVESTOR_ASK_NECESSIDADES -> pergunta suítes, diferenciais, vagas, situação
  5. INVESTOR_ASK_FINALIZACAO  -> pergunta pagamento + urgência + prioridades
  --- Score calculado ---
  6a. INVESTOR_QUENTE_OPCOES          -> apresenta perfil + opções (lead quente)
  6b. INVESTOR_QUENTE_ASK_VISITA      -> pergunta se quer agendar visita
  6c. INVESTOR_QUENTE_VISITA_CONFIRMADA -> confirma agendamento
  6d. INVESTOR_QUENTE_MAIS_OPCOES     -> mais opções (sem visita imediata)
  7a. INVESTOR_MORNO_SELECAO          -> informa seleção personalizada (lead morno)
  7b. INVESTOR_MORNO_CONSULTORIA      -> oferece consultoria financeira
  7c. INVESTOR_MORNO_DICA_VIP         -> dica VIP (contato parcial)
  8a. INVESTOR_FRIO_BARREIRA          -> identifica barreiras (lead frio)
  8b. INVESTOR_FRIO_PARCEIRO          -> indica parceiros (ticket abaixo R$400K)
  8c. INVESTOR_FRIO_NUTRICAO          -> encerra com nutrição ativa
"""

# ---------------------------------------------------------------------------
# Etapa 1 - Abertura
# ---------------------------------------------------------------------------

INVESTOR_INITIAL = (
    "Investimento em imóveis é uma ótima estratégia! 📝\n\n"
    "Você busca retorno com aluguel ou revenda no médio prazo?\n\n"
    "Isso vai me ajudar a focar nas melhores oportunidades para sua estratégia!"
)

# ---------------------------------------------------------------------------
# Etapa 2 - Tipo de imóvel
# ---------------------------------------------------------------------------

INVESTOR_ASK_TIPO_NOME = (
    "Para encontrar o imóvel ideal, me conta sobre suas preferências:\n\n"
    "Qual estilo você tem em mente?\n"
    "Apartamento de luxo, casa em condomínio fechado, cobertura...?"
)

# Etapa 2b - Nome (enviado apos pausa natural de 5s)
INVESTOR_ASK_NOME = (
    "E me conta, como é seu nome?\n"
    "Só pra eu te chamar direitinho 😊"
)

# ---------------------------------------------------------------------------
# Etapa 3 - Regiao + Faixa de investimento
# ---------------------------------------------------------------------------

INVESTOR_ASK_REGIAO = (
    "{nome}, qual região de Cuiabá você prefere?\n\n"
    "Temos opções incríveis no Jardim Itália, Despraiado, Quilombo, Duque de Caxias...\n"
    "Ou você tem outro bairro em mente?"
)

# Etapa 3b - Faixa de investimento (enviado apos pausa - digitar)
# {nome} deve ser substituido pelo nome do lead
INVESTOR_ASK_INVESTIMENTO = (
    "{nome}, para eu selecionar as propriedades que mais se adequam ao seu perfil,\n"
    "qual faixa de investimento você considera?"
)

# ---------------------------------------------------------------------------
# Etapa 4 - Necessidades + Vagas + Situacao
# ---------------------------------------------------------------------------

INVESTOR_ASK_NECESSIDADES = (
    "Quantas suítes você precisa?\n"
    "E tem alguma preferência especial como closet, sala de cinema, espaço gourmet...?"
)

# Etapa 4b - Vagas de garagem (enviado apos pausa de 15s)
INVESTOR_ASK_VAGAS = (
    "Entendi! E quanto à garagem,\n"
    "quantas vagas você precisa?\n"
    "A maioria dos nossos imóveis tem de 2 a 4 vagas cobertas..."
)

# Etapa 4c - Situacao do imovel (pronto vs lancamento)
INVESTOR_ASK_SITUACAO = (
    "Outra questão importante:\n\n"
    "Você prefere uma propriedade pronta para morar, "
    "ou tem interesse em lançamentos exclusivos?\n\n"
    "Temos alguns empreendimentos novos com condições especiais de lançamento..."
)

# ---------------------------------------------------------------------------
# Etapa 5 - Fechamento da coleta (pagamento + urgencia + prioridades)
# ---------------------------------------------------------------------------

INVESTOR_ASK_FINALIZACAO = (
    "Uma última questão para eu te orientar da melhor forma:\n\n"
    "Como você planeja realizar o investimento?\n"
    "À vista, financiamento, permuta com outro imóvel, ou tem alguma estratégia específica?"
)

# Etapa 5b - Prazo ideal
# {nome} deve ser substituido pelo nome do lead
INVESTOR_ASK_PRAZO = (
    "{nome}, me ajuda a entender uma coisa:\n\n"
    "Qual é o seu prazo ideal?\n"
    "É algo urgente ou você prefere avaliar com calma?"
)

# Etapa 5c - Prioridades do imovel
# {nome} deve ser substituido pelo nome do lead
INVESTOR_ASK_PRIORIDADES = (
    "{nome}, me conta: o que é essencial para você nesta propriedade?\n"
    "Segurança 24h? Área de lazer completa? Vista privilegiada? Privacidade? "
    "Me ajuda a entender suas prioridades..."
)

# ---------------------------------------------------------------------------
# Etapa 6 - Lead QUENTE (80-100 pts)
# ---------------------------------------------------------------------------

INVESTOR_QUENTE_OPCOES = (
    "{nome}, analisando seu perfil, identifiquei algumas propriedades que combinam "
    "perfeitamente com o que você busca! 🎉\n\n"
    "Posso te apresentar agora mesmo algumas opções exclusivas? "
    "Tenho certeza que você vai adorar..."
)

# Follow-up enviado 10min apos INVESTOR_QUENTE_OPCOES (sem resposta do lead)
# {nome} deve ser substituido pelo nome do lead
INVESTOR_QUENTE_FOLLOWUP = (
    "{nome}, ainda está por aqui? 👀\n\n"
    "Tenho algumas opções exclusivas esperando por você! "
    "São propriedades de alto padrão com tudo que você me descreveu. "
    "Posso te mostrar agora?"
)

INVESTOR_QUENTE_ASK_VISITA = (
    "Esses imóveis estão com alta demanda. "
    "Para garantir o melhor atendimento, "
    "posso agendar uma visita exclusiva com nosso consultor especializado?\n\n"
    "Qual data e horário são melhores para você?"
)

INVESTOR_QUENTE_VISITA_CONFIRMADA = (
    "Visita agendada! "
    "Nosso consultor entrará em contato em breve para confirmar todos os detalhes.\n\n"
    "Qualquer dúvida, estou por aqui!"
)

INVESTOR_QUENTE_MAIS_OPCOES = (
    "Vou adorar te receber para visita pessoal.\n"
    "Nosso consultor pode te acompanhar e mostrar todos os detalhes...\n\n"
    "Que dia e horário seria melhor para você?\n"
    "Podemos agendar ainda esta semana?"
)

# Novas opcoes ajustadas apos lead informar barreira
# {nome} deve ser substituido pelo nome do lead
INVESTOR_QUENTE_NOVAS_OPCOES = (
    "Entendido, {nome}! Vou ajustar a busca com base no seu feedback.\n\n"
    "Já estou refinando as opções para você. "
    "Em instantes vou te apresentar alternativas mais alinhadas. "
    "O que acha dessas novas sugestões?"
)

# Reacao: lead nao gostou das opcoes apresentadas
INVESTOR_QUENTE_NAO_GOSTOU = (
    "Entendo! Me ajuda a refinar a busca:\n\n"
    "O que não te agradou nessas opções?\n"
    "□ Preço está alto\n"
    "□ Localização não é ideal\n"
    "□ Tamanho não atende\n"
    "□ Acabamento não é o esperado\n"
    "□ Outro motivo"
)

# ---------------------------------------------------------------------------
# Etapa 7 - Lead MORNO (50-79 pts)
# ---------------------------------------------------------------------------

INVESTOR_MORNO_SELECAO = (
    "{nome}, foi um prazer conversar com você! 😊\n\n"
    "Vou preparar uma seleção personalizada de propriedades "
    "e envio para você ainda hoje.\n\n"
    "Prefere receber via WhatsApp ou e-mail?\n"
    "Me passa seu melhor contato?"
)

# Enviado quando lead escolhe receber por e-mail
INVESTOR_MORNO_ASK_EMAIL = (
    "Qual é o seu e-mail?\n"
    "Vou enviar a seleção completa com fotos, plantas e valores 😊"
)

# Enviado quando lead escolhe receber por WhatsApp
INVESTOR_MORNO_ASK_WHATS = (
    "Posso enviar nesse mesmo número ou prefere outro WhatsApp?"
)

INVESTOR_MORNO_CONSULTORIA = (
    "Obrigada! Vou enviar a seleção em breve.\n\n"
    "Além disso, nossa equipe oferece uma *consultoria financeira gratuita* "
    "para ajudar a definir a melhor estratégia de investimento. "
    "Gostaria de agendar uma conversa rápida com nosso especialista?"
)

INVESTOR_MORNO_DICA_VIP = (
    "Obrigada! Vou te enviar a seleção.\n\n"
    "Enquanto isso, deixa eu te dar uma *dica VIP*: "
    "os imóveis com maior retorno de aluguel em Cuiabá são os de 2-3 suítes "
    "em regiões como Despraiado e Jardim Itália, com retorno médio de 0,5% ao mês. "
    "Qualquer dúvida, estou à disposição!"
)

# ---------------------------------------------------------------------------
# Etapa 8 - Lead FRIO (0-49 pts)
# ---------------------------------------------------------------------------

INVESTOR_FRIO_BARREIRA = (
    "{nome}, entendo que você quer avaliar com calma! Isso é super importante 😊\n\n"
    "O que te impede de avançar agora?\n"
    "É questão de orçamento, timing, ou quer conhecer melhor o mercado?"
)

INVESTOR_FRIO_PARCEIRO = (
    "Obrigada pelo contato, {nome}! "
    "Nossa especialidade são imóveis acima de R$ 400 mil, "
    "mas posso te indicar parceiros excelentes que trabalham com "
    "outras faixas de preço e vão te atender muito bem!\n\n"
    "Posso te passar o contato deles?"
)

# Barreira: questao financeira/orcamento
# {nome} deve ser substituido pelo nome do lead
INVESTOR_FRIO_FINANCEIRA = (
    "Que tal marcarmos uma conversa com nosso consultor financeiro? "
    "Ele pode te mostrar alternativas que talvez você não conheça!\n\n"
    "É gratuito e sem compromisso .."
)

# Barreira: timing / nao e o momento
INVESTOR_FRIO_TIMING = (
    "Sem problema! Vou te adicionar na nossa lista VIP. "
    "Quando surgir algo perfeito pra você, te aviso na hora! 🔔\n\n"
    "Enquanto isso, posso te enviar nosso guia exclusivo sobre o mercado em Cuiabá."
)

# Barreira: quer conhecer melhor o mercado
INVESTOR_FRIO_CONHECIMENTO = (
    "Olha, temos um showroom incrível!\n\n"
    "Que tal conhecer pessoalmente? Você pode ver os acabamentos, tirar dúvidas...\n\n"
    "Não é compromisso, é só pra você se familiarizar. Que dia você consegue?"
)

# ---------------------------------------------------------------------------
# Nutricao sequencial FRIO (1d / 7d / 15d / 30d)
# Handlers desativados (_NURTURE_ACTIVE=False) ate conteudo definitivo ser aprovado.
# ---------------------------------------------------------------------------

# Dia 1 — Boas-vindas + Guia do Mercado (mensagem estatica)
# TODO: substituir pelo conteudo definitivo quando aprovado
INVESTOR_NURTURE_1D = (
    "TODO: Dia 1 — Boas-vindas + Guia do Mercado"
)

# Dia 7 — Novidades + Dicas (mensagem estatica)
# TODO: substituir pelo conteudo definitivo quando aprovado
INVESTOR_NURTURE_7D = (
    "TODO: Dia 7 — Novidades + Dicas"
)

# Dia 15 — Prompt de sistema para LLM gerar mensagem personalizada
# Campos: {nome}, {regiao}, {investimento}, {barreira}
INVESTOR_NURTURE_15D_SYSTEM = (
    "Você é a assistente Andreia Perez, especialista em imóveis de alto padrão em Cuiabá.\n"
    "Crie uma mensagem WhatsApp curta (máximo 3 parágrafos) de nutrição para o lead {nome}.\n"
    "Contexto do lead: regiao={regiao}, investimento={investimento}, barreira={barreira}.\n"
    "Tema: Oportunidades Exclusivas — destaque 1-2 diferenciais do mercado de Cuiabá.\n"
    "Tom: pessoal, caloroso, sem pressão. Não mencione que é automatizado."
)

# Dia 30 — Prompt de sistema para LLM gerar check-in personalizado
# Campos: {nome}, {regiao}, {investimento}, {barreira}
INVESTOR_NURTURE_30D_SYSTEM = (
    "Você é a assistente Andreia Perez, especialista em imóveis de alto padrão em Cuiabá.\n"
    "Crie uma mensagem WhatsApp curta (máximo 3 parágrafos) de check-in para o lead {nome}.\n"
    "Contexto do lead: regiao={regiao}, investimento={investimento}, barreira={barreira}.\n"
    "Tema: Check-in Personalizado — reconecte com o lead, pergunte se o cenário mudou.\n"
    "Tom: pessoal, sem pressão. Não mencione que é automatizado."
)

INVESTOR_FRIO_NUTRICAO = (
    "Vou te incluir em nossa lista VIP de novidades do mercado. "
    "Você vai receber atualizações exclusivas sobre lançamentos, "
    "oportunidades e tendências do mercado imobiliário de Cuiabá.\n\n"
    "Quando estiver pronto para dar o próximo passo, "
    "pode contar comigo! Até logo!"
)

# Contato do parceiro enviado quando lead tem budget abaixo de R$400k
INVESTOR_FRIO_CONTATO_PARCEIRO = (
    "Aqui está o contato de um parceiro de confiança:\n\n"
    "*João Rodrigues* — Imóveis Acessíveis MT\n"
    "📱 (65) 99234-5678\n\n"
    "Fala que a Andreia indicou, ele vai te atender muito bem! 😊"
)
