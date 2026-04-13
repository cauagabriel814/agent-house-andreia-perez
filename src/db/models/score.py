import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.lead import Base


class LeadScore(Base):
    __tablename__ = "lead_scores"
    __table_args__ = (
        Index("ix_lead_scores_lead_type", "lead_id", "score_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True)
    score_type: Mapped[str] = mapped_column(String(20), nullable=False)
    investimento_pts: Mapped[int] = mapped_column(default=0)
    pagamento_pts: Mapped[int] = mapped_column(default=0)
    urgencia_pts: Mapped[int] = mapped_column(default=0)
    situacao_pts: Mapped[int] = mapped_column(default=0)
    dados_pts: Mapped[int] = mapped_column(default=0)
    total_score: Mapped[int] = mapped_column(default=0)
    classification: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="scores")
