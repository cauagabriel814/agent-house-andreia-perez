import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.lead import Base

if TYPE_CHECKING:
    from src.db.models.lead import Lead
    from src.db.models.message import Message


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_lead_status", "lead_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    current_node: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    graph_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_lead_message_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    timeout_notified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")
