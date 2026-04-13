import re

from src.agent.state import AgentState

# Palavras/frases que indicam intenção clara — processamos no mesmo ciclo
_INTENT_KEYWORDS = {
    "comprar", "vender", "alugar", "investir", "investimento", "permuta",
    "trocar", "troca", "imovel", "imóvel", "casa", "apart", "terreno",
    "quero", "preciso", "busco", "procuro", "tenho", "interesse", "cobertura",
    "lançamento", "lancamento", "financiamento", "locação", "locacao",
    "anuncio", "anúncio", "empreendimento", "propried",
}

# Nodes de fluxo - continuam processando mensagens dentro do mesmo fluxo
_FLOW_NODES = {"generic", "sale", "rental", "investor", "exchange", "specific", "buyer", "launch"}

# Nodes que apos responder voltam para active_listen (nao continuam no mesmo fluxo)
_TRANSIENT_NODES = {"faq"}

# Sufixos que indicam que um fluxo foi encerrado e virou handoff pro corretor
_TERMINAL_SUFFIXES = ("_encerrado",)

# Mapeamento de prefixo de last_question → node do fluxo de qualificacao
_QUESTION_PREFIX_TO_NODE = {
    "sale_": "sale",
    "rental_": "rental",
    "investor_": "investor",
    "exchange_": "exchange",
    "specific_": "specific",
    "buyer_": "buyer",
    "launch_": "launch",
}


def route_entry(state: AgentState) -> str:
    """
    Funcao condicional: determina o node de entrada baseado no progresso da conversa.

    Logica:
    - message_type == "timeout" → timeout (evento injetado pelo scheduler, Feature 15)
    - Conversa nova (current_node vazio) → greeting
    - Apos saudacao enviada → active_listen (processa resposta do lead)
    - Apos escuta ativa → router (classifica a intencao)
    - Dentro de um fluxo especifico → mesmo fluxo (continua coleta de dados)
    - Apos timeout → greeting (reinicia o fluxo quando lead responde)
    """
    # Evento de timeout injetado pelo scheduler (Feature 15)
    if state.get("message_type") == "timeout":
        return "timeout"

    current_node = state.get("current_node") or ""

    if not current_node or current_node == "start":
        return "greeting"

    if current_node == "greeting":
        # Se havia fluxo ativo (lead retornou apos timeout), vai direto para o node correto
        # sem passar por active_listen -> router (que classificaria como "generico")
        last_q = state.get("last_question") or ""
        for prefix, node in _QUESTION_PREFIX_TO_NODE.items():
            if last_q.startswith(prefix):
                return node
        return "active_listen"

    if current_node in ("active_listen", "router"):
        return "router"

    # Conversa ja encerrada: qualquer mensagem vai para o completed_node
    if current_node == "completed":
        return "completed"

    last_q_terminal = state.get("last_question") or ""
    if any(last_q_terminal.endswith(suf) for suf in _TERMINAL_SUFFIXES):
        return "completed"

    if current_node in _FLOW_NODES:
        return current_node  # continua no fluxo atual

    if current_node in _TRANSIENT_NODES:
        # Se havia um fluxo ativo, retorna direto ao node correto sem passar pelo router
        last_q = state.get("last_question") or ""
        for prefix, node in _QUESTION_PREFIX_TO_NODE.items():
            if last_q.startswith(prefix):
                return node
        # Sem fluxo ativo: volta para escuta ativa para coletar intencao
        return "active_listen"

    if current_node == "timeout":
        return "greeting"  # reinicia apos timeout

    return "greeting"


def route_by_intent(state: AgentState) -> str:
    """Funcao condicional: roteia baseado na intencao detectada."""
    intent = state.get("detected_intent", "generico")

    # Clarificação: lead pediu esclarecimento da pergunta atual.
    # Roteamos de volta para o nó do fluxo ativo (identificado pelo last_question),
    # que irá re-explicar a pergunta via build_smart_redirect.
    if intent == "clarificacao":
        last_q = state.get("last_question") or ""
        for prefix, node in _QUESTION_PREFIX_TO_NODE.items():
            if last_q.startswith(prefix):
                return node
        # Sem fluxo ativo: trata como genérico
        return "generic"

    intent_map = {
        "venda": "sale",
        "locacao": "rental",
        "investidor": "investor",
        "permuta": "exchange",
        "interesse_especifico": "specific",
        "faq": "faq",
        "generico": "generic",
    }
    return intent_map.get(intent, "generic")


def _message_has_intent(message: str) -> bool:
    """Verifica se a mensagem contém palavras-chave de intenção clara."""
    msg_clean = re.sub(r"[^\w\s]", "", message.lower())
    return any(kw in msg_clean for kw in _INTENT_KEYWORDS)


def route_after_greeting(state: AgentState) -> str:
    """
    Apos saudacao em horario comercial.

    - Fora do horario -> end
    - Recovery de timeout (havia fluxo ativo) -> end
    - Mensagem com intencao clara (ex: "quero investir") -> active_listen (mesmo ciclo)
    - Saudacao pura sem intencao (ex: "Ola", "Oi") -> end (greeting ja perguntou
      "como posso ajudar?", aguarda proxima mensagem)
    """
    if not state.get("business_hours", True):
        return "end"

    # Recovery de timeout (havia fluxo ativo) -> aguarda proxima mensagem
    last_q = state.get("last_question") or ""
    if any(last_q.startswith(p) for p in _QUESTION_PREFIX_TO_NODE):
        return "end"

    # Se a mensagem tem intenção clara, processa no mesmo ciclo
    msg = state.get("current_message") or ""
    if _message_has_intent(msg):
        return "active_listen"

    # Saudação pura: greeting já enviou "Me conta, como posso te ajudar?"
    return "end"


def route_to_faq_or_end(state: AgentState) -> str:
    """
    Usado como edge condicional nos flow nodes.
    Se o node retornou current_node='faq' (lead fez pergunta sobre a empresa/processos),
    roteia para o faq_node processar a resposta neste mesmo turno.
    Caso contrário, vai para END normalmente.
    """
    return "faq" if state.get("current_node") == "faq" else "end"


def route_after_generic(state: AgentState) -> str:
    """
    Funcao condicional: decide o destino apos o node generic.

    - awaiting_response=True (enviou explicacao ou re-clarificacao) -> END
    - intencao identificada (venda/locacao/etc) -> fluxo correspondente
    - ainda generico ou encerramento -> END
    """
    awaiting = state.get("awaiting_response", False)
    if awaiting:
        return "end"

    intent = state.get("detected_intent", "generico")
    intent_map = {
        "venda": "sale",
        "locacao": "rental",
        "investidor": "investor",
        "permuta": "exchange",
        "interesse_especifico": "specific",
    }
    return intent_map.get(intent, "end")
