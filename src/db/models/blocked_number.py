import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.lead import Base


class BlockedNumber(Base):
    __tablename__ = "blocked_numbers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
