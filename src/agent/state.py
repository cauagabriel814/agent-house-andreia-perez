from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Identificacao
    phone: str
    lead_id: Optional[str]  # UUID serializado como string para compatibilidade JSONB
    conversation_id: Optional[str]  # UUID serializado como string

    # Mensagem atual
    current_message: str
    message_type: str  # text, audio, image, etc
    processed_content: Optional[str]

    # Contexto do lead
    lead_name: Optional[str]
    lead_email: Optional[str]
    is_recurring: bool
    classification: Optional[str]  # quente, morno, frio

    # Historico
    messages: Annotated[list, add_messages]
    conversation_history: list[dict]

    # Tags coletadas
    tags: dict[str, str]

    # Roteamento
    current_node: str
    detected_intent: Optional[str]
    # venda | locacao | investidor | permuta | interesse_especifico | faq | generico
    previous_intent: Optional[str]  # fluxo anterior quando lead troca de intenção

    # Scoring
    score_data: Optional[dict]
    total_score: Optional[int]

    # Controle de fluxo
    awaiting_response: bool
    last_question: Optional[str]
    timeout_count: int
    reask_count: int  # vezes que re-perguntamos a etapa atual; reset a 0 quando resposta válida

    # Pós-encerramento
    is_silenced: bool  # True quando fluxo terminou e corretor ja foi avisado

    # Metadados
    business_hours: bool
    utm_source: Optional[str]

    # KOMMO CRM
    kommo_contact_id: Optional[str]  # ID do contato no KOMMO
    kommo_lead_id: Optional[str]     # ID do negocio (deal) no KOMMO
