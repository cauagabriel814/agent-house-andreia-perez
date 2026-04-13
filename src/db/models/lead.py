import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from src.db.models.conversation import Conversation
    from src.db.models.message import Message
    from src.db.models.notification import Notification
    from src.db.models.scheduled_job import ScheduledJob
    from src.db.models.score import LeadScore
    from src.db.models.tag import LeadTag


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    origin: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    classification: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    score: Mapped[Optional[int]] = mapped_column(nullable=True)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    kommo_contact_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    kommo_lead_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="lead")
    messages: Mapped[list["Message"]] = relationship(back_populates="lead")
    tags: Mapped[list["LeadTag"]] = relationship(back_populates="lead")
    scores: Mapped[list["LeadScore"]] = relationship(back_populates="lead")
    scheduled_jobs: Mapped[list["ScheduledJob"]] = relationship(back_populates="lead")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="lead")
