"""
chat.py - Grafo simplificado para testes no LangGraph Studio.

Aceita apenas { phone, message } e inicializa todo o AgentState
internamente, exatamente como o runner.py faz em producao.
Retorna { response, node, intent } para facilitar a leitura no Studio.
"""

from typing import Annotated, Optional
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

from src.agent.graph import build_graph
from src.agent.state import AgentState


# ---------------------------------------------------------------------------
# State minimalista para o Studio
# ---------------------------------------------------------------------------

class ChatInput(TypedDict):
    phone: str
    message: str
    message_type: Optional[str]   # padrao: "text"
    current_node: Optional[str]   # padrao: "" (novo lead)


class ChatOutput(TypedDict):
    response: str
    node: str
    intent: Optional[str]
    awaiting: bool


# ---------------------------------------------------------------------------
# Node unico: inicializa estado e invoca o grafo principal
# ---------------------------------------------------------------------------

_agent_graph = build_graph()


async def run_chat(state: ChatInput) -> ChatOutput:
    phone        = state["phone"]
    message      = state["message"]
    msg_type     = state.get("message_type") or "text"
    current_node = state.get("current_node") or ""

    agent_state: AgentState = {
        "phone":                phone,
        "lead_id":              0,
        "conversation_id":      0,
        "current_message":      message,
        "message_type":         msg_type,
        "processed_content":    message,
        "lead_name":            None,
        "lead_email":           None,
        "is_recurring":         bool(current_node),
        "classification":       None,
        "messages":             [HumanMessage(content=message)],
        "conversation_history": [],
        "tags":                 {},
        "current_node":         current_node,
        "detected_intent":      None,
        "score_data":           None,
        "total_score":          None,
        "awaiting_response":    False,
        "last_question":        None,
        "timeout_count":        0,
        "business_hours":       True,
        "utm_source":           "studio_test",
    }

    result = await _agent_graph.ainvoke(agent_state)

    # Extrai ultima mensagem do agente
    ai_msgs = [m for m in result.get("messages", []) if isinstance(m, AIMessage)]
    response = ai_msgs[-1].content if ai_msgs else "(sem resposta)"

    return {
        "response":  response,
        "node":      result.get("current_node") or "",
        "intent":    result.get("detected_intent"),
        "awaiting":  bool(result.get("awaiting_response")),
    }


# ---------------------------------------------------------------------------
# Grafo com node unico exposto no Studio
# ---------------------------------------------------------------------------

def build_chat_graph():
    graph = StateGraph(ChatInput, output=ChatOutput)
    graph.add_node("chat", run_chat)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile()
