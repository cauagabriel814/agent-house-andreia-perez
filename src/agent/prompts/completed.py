"""
completed.py - Mensagens para conversas ja encerradas.

Quando um fluxo termina (lead agendou visita, foi escalado pro corretor, etc),
o agente envia UMA resposta educada se o lead continuar mandando mensagens, e
depois silencia completamente.
"""

COMPLETED_HANDOFF = (
    "Seu atendimento ja esta com nosso corretor especialista! 🤝\n\n"
    "Ele(a) vai te chamar em instantes por aqui mesmo. "
    "Se for urgente, pode aguardar que ja estamos com tudo em maos. 😊"
)
