"""
Prompts do fluxo de interesse específico, comprador e lançamento (Feature 14).

Sub-fluxo: Interesse Específico
  SPECIFIC_INITIAL           -> pergunta o que o lead procura / qual anúncio viu

Sub-fluxo: Comprador (qualificação de ticket)
  BUYER_ASK_TICKET           -> pergunta sobre faixa de investimento
  BUYER_FORA_PERFIL          -> mensagem para ticket abaixo de R$400K
  BUYER_ASK_TIPO             -> pergunta se busca lançamento ou imóvel pronto

Sub-fluxo: Lançamento
  LAUNCH_ASK_NOME            -> coleta nome -> TAG: lead_lancamento_identificado
  LAUNCH_APRESENTAR          -> apresenta o empreendimento
  LAUNCH_CONHECE_SIM         -> reforçar valorização (conhece a região)
  LAUNCH_CONHECE_NAO         -> apresentar vantagens do bairro (não conhece)
  LAUNCH_ASK_PLANTA          -> pergunta tipo de unidade -> TAG: planta_interesse
  LAUNCH_ASK_PAGAMENTO       -> pergunta forma de pagamento -> TAG: forma_pagamento_lancamento
  LAUNCH_ASK_URGENCIA        -> pergunta urgência -> TAG: urgencia_lancamento
  LAUNCH_ASK_CONTATO         -> coleta contato completo + lista VIP -> TAG: contato_completo_lancamento
  LAUNCH_QUENTE_AGENDAR      -> QUENTE: agendar apresentação com especialista (SLA 1h)
  LAUNCH_MORNO_MATERIAL      -> MORNO: enviar material completo + follow-up 24h

Sub-fluxo: Imovel Pronto
  PRONTO_ASK_NOME            -> coleta nome -> TAG: lead_imovel_especifico
  PRONTO_ASK_FAIXA_VALOR     -> pergunta faixa de investimento -> TAG: faixa_valor
  PRONTO_ASK_FORMA_PAGAMENTO -> pergunta forma de pagamento -> TAG: forma_pagamento
  PRONTO_ASK_URGENCIA        -> pergunta prazo/urgência -> TAG: urgencia
  PRONTO_ASK_PRIORIDADES     -> pergunta prioridades (segurança, lazer, vista...) -> TAG: prioridades
  PRONTO_APRESENTAR          -> apresenta e pergunta preferências (região + suítes)
  PRONTO_APRESENTAR_DETALHES -> detalha opções e pergunta se quer visitar
  PRONTO_AGENDAR_VISITA      -> solicita data/horário da visita
  PRONTO_VISITA_CONFIRMADA   -> confirma agendamento da visita
  PRONTO_ASK_BARREIRA        -> identifica barreira quando não quer visitar (Secao 3.5 PDF)
  PRONTO_BARREIRA_FINANCEIRA -> TAG: consultoria_agendada — oferecer consultor financeiro gratuito
  PRONTO_BARREIRA_TIMING     -> TAG: lista_vip — lista VIP + nutrição automática
  PRONTO_BARREIRA_CONHECIMENTO -> TAG: tour_agendado — convidar para showroom presencial
  PRONTO_MATERIAL_DIGITAL    -> coleta email e envia material digital
"""

# ---------------------------------------------------------------------------
# Interesse Especifico
# ---------------------------------------------------------------------------

SPECIFIC_INITIAL = (
    "Você viu algum anúncio específico nosso? "
    "Ou está procurando em geral?"
)

SPECIFIC_ASK_EMPREENDIMENTO = (
    "Ah, que legal! 🏠\n\n"
    "Qual empreendimento chamou sua atenção?"
)

# ---------------------------------------------------------------------------
# Comprador
# ---------------------------------------------------------------------------

BUYER_ASK_TICKET = (
    "Qual faixa de investimento você considera para este imóvel?"
)

BUYER_ASK_PREFERENCIAS = (
    "Excelente! Para encontrar o imóvel ideal, me conta sobre suas preferências:\n\n"
    "Qual estilo você tem em mente? Apartamento de luxo, casa em condomínio fechado, cobertura...?"
)

BUYER_FORA_PERFIL = (
    "{nome}Muito obrigada pelo contato! 🙏\n\n"
    "Nossa especialidade são imóveis acima de R$ 400 mil. "
    "Para a faixa que você procura, posso te indicar parceiros excelentes!\n\n"
    "Posso te passar o contato?"
)

BUYER_FORA_PERFIL_CONTATO = (
    "Claro! Segue o contato:\n\n"
    "👤 *Carlos Henrique*\n"
    "📱 (65) 99210-4832\n\n"
    "Ele atende exatamente o seu perfil e vai te ajudar muito bem! 😊"
)

BUYER_ASK_TIPO = (
    "Você prefere um *imóvel pronto para morar* "
    "ou tem interesse em um *lançamento* "
    "(imóvel na planta ou em construção, com condições diferenciadas de pagamento)?"
)

# ---------------------------------------------------------------------------
# Lancamento
# ---------------------------------------------------------------------------

LAUNCH_ASK_NOME = (
    "{empreendimento} é um lançamento incrível! 🏠\n\n"
    "Vi que você se interessou. Deixa eu te contar mais sobre ele!\n\n"
    "Primeiro, qual seu nome?"
)

LAUNCH_APRESENTAR = (
    "{nome}, o {empreendimento} é um lançamento exclusivo no {regiao}. "
    "Deixa eu te passar os destaques:\n\n"
    "📍 Localização privilegiada\n"
    "📅 Entrega prevista: {entrega}\n"
    "🛏 {suites} suítes com {diferenciais}\n"
    "✨ Acabamento de alto padrão\n"
    "💰 Condições especiais de lançamento\n\n"
    "Você já conhece a região?"
)

LAUNCH_CONHECE_SIM = (
    "Então você já conhece bem a região! 😊\n\n"
    "É um dos bairros mais procurados de Cuiabá, com ótima infraestrutura e qualidade de vida."
)

LAUNCH_CONHECE_NAO = (
    "Deixa eu te contar sobre o {regiao}:\n\n"
    "É um bairro com excelente infraestrutura, muito bem localizado e alta demanda em Cuiabá. "
    "{pontos_destaque}\n\n"
    "O empreendimento fica a {distancia} de {pontos_referencia}."
)

LAUNCH_ASK_PLANTA = (
    "Agora me conta:\n\n"
    "Qual tipo de unidade te interessa mais?\n"
    "Temos plantas de {tipos_unidade} suítes "
    "com metragens de {metragem_min} a {metragem_max}m\u00b2"
)

LAUNCH_ASK_PAGAMENTO = (
    "{nome}, como você pretende investir nesse lançamento?\n\n"
    "Temos condições exclusivas:\n"
    "• Entrada facilitada\n"
    "• Parcelas direto com a construtora\n"
    "• Possibilidade de uso do FGTS\n"
    "• Descontos para pagamento à vista"
)

LAUNCH_ASK_URGENCIA = (
    "E qual seu prazo para decisão?\n\n"
    "Pergunto porque temos condições especiais de lançamento "
    "que são por tempo limitado e algumas unidades já estão reservadas."
)

LAUNCH_ASK_CONTATO = (
    "{nome}, vou te adicionar na lista VIP do lançamento! 🎉\n\n"
    "Me passa seu WhatsApp e e-mail para eu enviar todo o material exclusivo:\n"
    "• Plantas e decorados\n"
    "• Tabela de preços atualizada\n"
    "• Tour virtual 360°\n"
    "• Simulação financeira personalizada"
)

LAUNCH_QUENTE_AGENDAR = (
    "{nome}, vou fazer o seguinte: 🎯\n\n"
    "Vou agendar uma apresentação exclusiva do lançamento "
    "para você com nosso especialista.\n\n"
    "Ele vai mostrar o decorado, explicar todas as condições "
    "e você pode tirar todas as dúvidas.\n\n"
    "Amanhã ou depois de amanhã, qual o melhor dia pra você?"
)

LAUNCH_MORNO_MATERIAL = (
    "{nome}, vou te enviar todo o material agora mesmo! 📦\n\n"
    "Dá uma olhada com calma e depois me conta o que achou.\n\n"
    "Qualquer dúvida é só me chamar!\n"
    "Em 24h eu retorno pra ver se você precisa de mais alguma informação."
)

LAUNCH_MATERIAL_IMOVEL = (
    "*{empreendimento}*\n"
    "📍 {regiao}\n\n"
    "🛏 {suites} | 📐 {metragem_min} a {metragem_max}m²\n"
    "🚗 {vagas} vagas cobertas\n"
    "📅 Entrega: {entrega}\n\n"
    "✨ *Diferenciais:*\n"
    "{diferenciais}\n\n"
    "💰 A partir de R$ {preco_inicial}"
)

# ---------------------------------------------------------------------------
# Imovel Pronto
# ---------------------------------------------------------------------------

PRONTO_ASK_NOME = (
    "Para te apresentar as melhores opções, qual seu nome?"
)

PRONTO_APRESENTAR_IMOVEL = (
    "{nome}, sobre esse imóvel:\n\n"
    "📍 {endereco}\n"
    "🏠 {suites} suítes, {metragem}m\u00b2\n"
    "🚗 {vagas} vagas cobertas\n"
    "💎 {diferenciais}\n"
    "💰 Valor: R$ {preco}\n\n"
    "Quer que eu envie fotos completas e um tour virtual?"
)

PRONTO_ASK_FAIXA_VALOR = (
    "{nome}, para eu filtrar as melhores opções do nosso portfólio, "
    "qual faixa de investimento você considera?\n\n"
    "Por exemplo: R$ 400k-600k, R$ 600k-1M, acima de R$ 1M..."
)

PRONTO_ASK_FORMA_PAGAMENTO = (
    "Como você pretende realizar o pagamento?\n\n"
    "- *À vista* (desconto especial)\n"
    "- *Financiamento bancário*\n"
    "- *Permuta* (troca de imóvel)\n"
    "- Outra estratégia?\n\n"
    "Isso me ajuda a indicar as melhores condições para o seu perfil."
)

PRONTO_ASK_URGENCIA = (
    "Qual seria o seu prazo ideal para fechar o negócio?\n\n"
    "Precisa com urgência (até 30 dias), tem entre 1 e 3 meses, "
    "ou está pesquisando com mais calma?"
)

PRONTO_ASK_PRIORIDADES = (
    "O que é mais importante para você no imóvel?\n\n"
    "Por exemplo: segurança 24h, lazer completo, vista privilegiada, "
    "privacidade, localização, acabamento premium... "
    "Me conta o que não pode faltar!"
)

PRONTO_ASK_BARREIRA = (
    "Entendido! Me conta um pouco mais:\n\n"
    "O que está te impedindo de agendar uma visita agora? "
    "É uma questão de orçamento, prazo ou você prefere conhecer mais opções antes?"
)

PRONTO_BARREIRA_FINANCEIRA = (
    "Entendo! Posso te conectar com nosso especialista financeiro "
    "para uma conversa rápida e totalmente gratuita, sem nenhum compromisso.\n\n"
    "Ele pode te ajudar a estruturar o melhor caminho para o seu investimento: "
    "financiamento, FGTS, consórcio ou outras estratégias. "
    "Seria útil para você?"
)

PRONTO_BARREIRA_TIMING = (
    "Sem pressa! Vou te incluir na nossa *Lista VIP* e te manter informado(a) "
    "sobre as melhores oportunidades do mercado.\n\n"
    "Quando o momento chegar, você vai estar à frente de todo mundo "
    "com as melhores opções já separadas. Pode contar comigo!"
)

PRONTO_BARREIRA_CONHECIMENTO = (
    "Que tal uma visita ao nosso *showroom*?\n\n"
    "É uma experiência incrível para conhecer de perto a qualidade, "
    "os acabamentos e os diferenciais dos nossos imóveis — sem pressão alguma.\n\n"
    "Quando você teria disponibilidade para uma visita de uns 30 minutos?"
)

PRONTO_APRESENTAR = (
    "{nome}, para te indicar as melhores alternativas "
    "do nosso portfólio, me conta um pouco mais:\n\n"
    "Qual região de Cuiabá você prefere? "
    "E quantas suítes são necessárias?"
)

PRONTO_APRESENTAR_DETALHES = (
    "Quer agendar uma visita para conhecer o imóvel pessoalmente? 🏠\n\n"
    "Nosso corretor pode te mostrar todos os detalhes, tirar suas dúvidas "
    "e te ajudar a encontrar as melhores condições."
)

PRONTO_AGENDAR_VISITA = (
    "Quando é melhor pra você?\n\n"
    "Nosso corretor pode te encontrar lá e mostrar todos os detalhes pessoalmente."
)

PRONTO_VISITA_CONFIRMADA = (
    "Visita agendada! Nosso corretor vai confirmar "
    "todos os detalhes por aqui em breve.\n\n"
    "Qualquer dúvida, estou à disposição. Até lá, {nome}!"
)

PRONTO_MATERIAL_DIGITAL = (
    "Vou te enviar agora:\n"
    "✅ Álbum completo de fotos\n"
    "✅ Tour virtual 360°\n"
    "✅ Planta baixa\n"
    "✅ Informações do condomínio\n\n"
    "Você consegue fazer uma visita presencial?\n"
    "Posso agendar ainda esta semana!"
)
