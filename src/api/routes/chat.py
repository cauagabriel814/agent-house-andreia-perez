from fastapi import APIRouter
from pydantic import BaseModel

from src.agent.runner import run_agent
from langchain_core.messages import AIMessage

router = APIRouter()


class ChatRequest(BaseModel):
    phone: str
    message: str
    message_type: str = "text"


class ChatResponse(BaseModel):
    response: str
    node: str
    intent: str | None
    awaiting: bool


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """Testa o agente diretamente — sem WhatsApp, sem fila."""
    result = await run_agent(
        phone=body.phone,
        message=body.message,
        message_type=body.message_type,
    )

    ai_msgs = [m for m in result.get("messages", []) if isinstance(m, AIMessage)]
    response = ai_msgs[-1].content if ai_msgs else "(sem resposta)"

    return ChatResponse(
        response=response,
        node=result.get("current_node") or "",
        intent=result.get("detected_intent"),
        awaiting=bool(result.get("awaiting_response")),
    )
