import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.conversation import Conversation


class ConversationService:
    """Gerenciamento de conversas."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, conversation_id: str | uuid.UUID) -> Optional[Conversation]:
        result = await self.session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_lead(self, lead_id: str | uuid.UUID) -> Optional[Conversation]:
        """Busca a conversa ativa mais recente do lead."""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.lead_id == lead_id, Conversation.status == "active")
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_create_active(self, lead_id: str | uuid.UUID) -> tuple[Conversation, bool]:
        """Busca conversa ativa ou cria nova. Retorna (conversa, criada)."""
        conv = await self.get_active_by_lead(lead_id)
        if conv:
            return conv, False
        conv = await self.create(lead_id)
        return conv, True

    async def create(self, lead_id: str | uuid.UUID) -> Conversation:
        conv = Conversation(lead_id=lead_id, status="active")
        self.session.add(conv)
        await self.session.commit()
        await self.session.refresh(conv)
        return conv

    async def update_graph_state(
        self,
        conversation: Conversation,
        graph_state: dict[str, Any],
        current_node: str,
    ) -> Conversation:
        """Persiste o state do LangGraph e o node atual."""
        conversation.graph_state = graph_state
        conversation.current_node = current_node
        conversation.last_message_at = datetime.now(timezone.utc).replace(tzinfo=None)
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def touch(self, conversation: Conversation) -> Conversation:
        """Atualiza last_message_at para o momento atual."""
        conversation.last_message_at = datetime.now(timezone.utc).replace(tzinfo=None)
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return conversation

    async def close(self, conversation: Conversation) -> Conversation:
        conversation.status = "closed"
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return conversation

    async def touch_lead_message(self, conversation: Conversation) -> Conversation:
        """
        Registra o timestamp da ultima mensagem REAL do lead.

        Diferente de last_message_at (que e atualizado por qualquer evento,
        incluindo timeouts), este campo so e atualizado quando o lead envia
        uma mensagem genuina. Usado pelo scheduler para verificar se o lead
        respondeu desde que um job foi agendado (Feature 16).
        """
        conversation.last_lead_message_at = datetime.now(timezone.utc).replace(tzinfo=None)
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return conversation

    async def mark_timeout_notified(self, conversation: Conversation) -> Conversation:
        conversation.timeout_notified = True
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        return conversation
