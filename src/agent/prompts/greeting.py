GREETING_NEW_LEAD = [
    "Oi! Tudo bem? 😊\nAqui é a Marina da Casa Andreia Perez!",
    "Que prazer ter você aqui!\nSomos especialistas em imóveis de alto padrão em Cuiabá.",
    "Me conta, como posso te ajudar hoje?",
]

# Prompt para saudação contextual gerada por LLM (lead novo)
GREETING_SMART_SYSTEM = """Você é a Marina, assistente virtual da Casa Andreia Perez, imobiliária especializada em imóveis de alto padrão em Cuiabá/MT.

Gere UMA ÚNICA mensagem de boas-vindas curta em português brasileiro para WhatsApp.

Regras obrigatórias:
- Máximo 2 linhas
- Tom caloroso e profissional
- Apresente-se sempre: "Aqui é a Marina da Casa Andreia Perez!"
- NUNCA mencione o assunto ou intenção do lead — isso será tratado na sequência
- NUNCA faça perguntas na saudação
- Máximo 1 emoji"""

GREETING_SMART_USER = "Gere apenas a saudação de boas-vindas (ignore o conteúdo, apenas dê boas-vindas): \"{message}\""

GREETING_RECURRING_LEAD = [
    "Oi {name}! Que bom te ver novamente! 😊",
    "Vi que você já conversou conosco sobre {interest} em {region}.",
    "Quer continuar de onde paramos ou mudou algo no que está procurando?",
]

GREETING_OUT_OF_HOURS = (
    "Oi! Que bom te ver por aqui! No momento estamos fora do horário, "
    "mas fiquei com sua mensagem! Amanhã às 9h retorno o contato. "
    "Enquanto isso, me conta: o que você procura? Vou deixar tudo anotado!"
)

GREETING_RETORNO_9H = (
    "Bom dia, {nome}! Como prometido, estou de volta! "
    "Vi que você entrou em contato ontem. "
    "Posso te ajudar a encontrar o imóvel perfeito agora? "
    "Me conta o que você está procurando!"
)
