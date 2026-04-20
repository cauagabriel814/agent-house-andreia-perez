from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.edges.conditions import route_after_ai_fallback, route_after_generic, route_after_greeting, route_by_intent, route_entry, route_to_faq_or_end
from src.agent.nodes.active_listen import active_listen_node
from src.agent.nodes.buyer import buyer_node
from src.agent.nodes.completed import completed_node
from src.agent.nodes.exchange import exchange_node
from src.agent.nodes.generic import generic_node
from src.agent.nodes.human_fallback import human_fallback_node
from src.agent.nodes.greeting import greeting_node
from src.agent.nodes.investor import investor_node
from src.agent.nodes.launch import launch_node
from src.agent.nodes.rental import rental_node
from src.agent.nodes.router import router_node
from src.agent.nodes.sale import sale_node
from src.agent.nodes.specific import specific_node
from src.agent.nodes.faq import faq_node
from src.agent.nodes.timeout import timeout_node
from src.agent.state import AgentState

# Destinos possiveis apos route_entry
_ENTRY_ROUTES = {
    "greeting": "greeting",
    "active_listen": "active_listen",
    "router": "router",
    "generic": "generic",
    "ai_fallback": "ai_fallback",
    "faq": "faq",
    "sale": "sale",
    "rental": "rental",
    "investor": "investor",
    "exchange": "exchange",
    "specific": "specific",
    "buyer": "buyer",
    "launch": "launch",
    "timeout": "timeout",
    "completed": "completed",
}

# Destinos possiveis apos route_by_intent
_INTENT_ROUTES = {
    "generic": "generic",
    "faq": "faq",
    "sale": "sale",
    "rental": "rental",
    "investor": "investor",
    "exchange": "exchange",
    "specific": "specific",
}

# Destinos possiveis apos greeting (horario comercial ou nao)
_GREETING_ROUTES = {
    "end": END,
    "active_listen": "active_listen",
}

# Destinos possiveis apos generic (re-classificacao de intencao)
_GENERIC_ROUTES = {
    "end": END,
    "sale": "sale",
    "rental": "rental",
    "investor": "investor",
    "exchange": "exchange",
    "specific": "specific",
    "ai_fallback": "ai_fallback",
}

# Destinos possiveis apos ai_fallback
_AI_FALLBACK_ROUTES = {
    "end": END,
    "sale": "sale",
    "rental": "rental",
    "investor": "investor",
    "exchange": "exchange",
    "specific": "specific",
    "completed": "completed",
}


def build_graph() -> CompiledStateGraph:
    """
    Constroi e compila o grafo principal do agente Andreia.

    Estrutura:
        START --> [route_entry] --> greeting | active_listen | router | <fluxo>
        greeting     --> END          (aguarda proxima mensagem do lead)
        active_listen --> router      (analisa resposta e detecta intencao)
        router       --> [route_by_intent] --> generic | sale | rental | investor | exchange | specific
        generic      --> [route_after_generic] --> END (aguardando) | sale | rental | investor | exchange | specific
        specific     --> END          (pode transicionar para buyer via state)
        buyer        --> END          (pode transicionar para launch via state)
        launch       --> END          (calcula score e encerra)
        <outros fluxos> --> END       (processa e responde; logica em Features 10-14)
        timeout      --> END          (trata inatividade; logica em Feature 15)
    """
    graph = StateGraph(AgentState)

    # --- Nodes ---
    graph.add_node("greeting", greeting_node)
    graph.add_node("active_listen", active_listen_node)
    graph.add_node("router", router_node)
    graph.add_node("generic", generic_node)
    graph.add_node("ai_fallback", human_fallback_node)
    graph.add_node("sale", sale_node)
    graph.add_node("rental", rental_node)
    graph.add_node("investor", investor_node)
    graph.add_node("exchange", exchange_node)
    graph.add_node("specific", specific_node)
    graph.add_node("buyer", buyer_node)
    graph.add_node("launch", launch_node)
    graph.add_node("faq", faq_node)
    graph.add_node("timeout", timeout_node)
    graph.add_node("completed", completed_node)

    # --- Edges ---

    # Entrada condicional: decide onde retomar a conversa
    graph.add_conditional_edges(START, route_entry, _ENTRY_ROUTES)

    # Apos saudacao: em horario comercial processa a mensagem inicial; fora do horario encerra
    graph.add_conditional_edges("greeting", route_after_greeting, _GREETING_ROUTES)

    # Apos escuta ativa: classifica intencao no router
    graph.add_edge("active_listen", "router")

    # Router decide qual fluxo ativar
    graph.add_conditional_edges("router", route_by_intent, _INTENT_ROUTES)

    # Generic roteia para fluxo correto apos re-classificar intencao (Feature 9)
    graph.add_conditional_edges("generic", route_after_generic, _GENERIC_ROUTES)

    # AI Fallback: agente IA humano para contextos nao resolvidos pelo generic
    graph.add_conditional_edges("ai_fallback", route_after_ai_fallback, _AI_FALLBACK_ROUTES)

    # Destinos possíveis para flow nodes que podem desviar para FAQ
    _FLOW_OR_FAQ = {"faq": "faq", "end": END}

    # Flow nodes: terminam em END normalmente, mas podem desviar para FAQ
    # quando o lead faz uma pergunta sobre a empresa/processos no meio do fluxo
    graph.add_conditional_edges("sale", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("rental", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("investor", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("exchange", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("specific", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("buyer", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_conditional_edges("launch", route_to_faq_or_end, _FLOW_OR_FAQ)
    graph.add_edge("faq", END)
    graph.add_edge("timeout", END)
    graph.add_edge("completed", END)

    return graph.compile()
