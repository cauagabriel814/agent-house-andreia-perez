import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.lead import Base


class KnowledgeChunk(Base):
    """Chunk de texto da knowledge base com embedding vetorial (pgvector)."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # embedding é gerenciado via SQL raw (pgvector vector(1536)) — não mapeado aqui
    # para evitar dependência do pgvector.sqlalchemy no ORM async
