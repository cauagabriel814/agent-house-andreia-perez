"""
test_agent.py - Testa o agente Andreia diretamente, sem precisar do WhatsApp.

Uso:
    .venv/Scripts/python.exe scripts/test_agent.py

O script simula uma conversa completa com o agente e envia os traces para o
LangSmith. Abra https://smith.langchain.com -> projeto andreia-residere para
acompanhar em tempo real.

Obs: as mensagens de resposta nao serao enviadas via WhatsApp (uazapi retorna
erro se a instancia nao estiver configurada). O importante aqui e ver o grafo
executar e os traces aparecendo no LangSmith.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config.settings import settings

# Ativa LangSmith ANTES de qualquer import do langchain
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

from src.agent.runner import run_agent  # noqa: E402

# ---------------------------------------------------------------------------
# Conversa de teste - altere as mensagens conforme quiser
# ---------------------------------------------------------------------------

PHONE_TEST = "5565988887777"  # numero ficticio

MENSAGENS = [
    ("text", "Oi"),                              # 1. Saudacao inicial
    ("text", "Quero comprar um apartamento"),    # 2. Intencao de venda
    ("text", "Tenho interesse em 2 quartos"),    # 3. Detalhe do imovel
]


async def simular_conversa():
    print("=" * 60)
    print(f"TESTE DO AGENTE ANDREIA")
    print(f"Projeto LangSmith: {settings.langchain_project}")
    print(f"Telefone simulado: {PHONE_TEST}")
    print("=" * 60)
    print()

    # Mock 1: metodo HTTP do servico UAZAPI - evita chamada real ao WhatsApp.
    #   Precisa ser no metodo da classe (nao na funcao importada pelos nodes)
    #   pois cada node faz `from src.agent.tools.uazapi import send_whatsapp_message`
    #   ja no momento do import, entao patches no modulo tools nao tem efeito.
    # Mock 2: is_business_hours - forca horario comercial para o teste nao bloquear
    #   (greeting_node chama a funcao diretamente, nao le do state)
    # Remova os mocks se quiser testar com instancia UAZAPI real configurada.
    with (
        patch(
            "src.services.uazapi.UazapiService.send_text_message",
            new_callable=AsyncMock,
            return_value={"status": "sent"},
        ),
        patch(
            "src.agent.nodes.greeting.is_business_hours",
            return_value=True,
        ),
    ):
        for i, (msg_type, mensagem) in enumerate(MENSAGENS, 1):
            print(f"[{i}/{len(MENSAGENS)}] Lead: {mensagem!r}")
            print("-" * 40)

            try:
                result = await run_agent(
                    phone=PHONE_TEST,
                    message=mensagem,
                    message_type=msg_type,
                    utm_source="teste_local",
                )

                print(f"  Node final:    {result.get('current_node') or '(vazio)'}")
                print(f"  Intencao:      {result.get('detected_intent') or '(nenhuma)'}")
                print(f"  Aguardando:    {result.get('awaiting_response')}")
                print(f"  Ultima pergunta: {result.get('last_question') or '(nenhuma)'}")
                print(f"  Score total:   {result.get('total_score') or '(sem score)'}")

                # Mostra ultima resposta do agente
                msgs = result.get("messages", [])
                from langchain_core.messages import AIMessage
                ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]
                if ai_msgs:
                    ultimo = ai_msgs[-1].content
                    print(f"  Andreia disse: {ultimo[:120]}{'...' if len(ultimo) > 120 else ''}")

            except Exception as exc:
                print(f"  ERRO: {type(exc).__name__}: {exc}")

            print()
            await asyncio.sleep(1)  # pausa entre mensagens

    print("=" * 60)
    print("Conversa concluida.")
    print(f"Veja os traces em: https://smith.langchain.com")
    print(f"Projeto: {settings.langchain_project}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(simular_conversa())
