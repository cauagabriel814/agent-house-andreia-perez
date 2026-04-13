"""add_last_lead_message_at

Revision ID: b3c7d9e1f204
Revises: 2fe1aa3d570f
Create Date: 2026-03-24 00:00:00.000000

Adiciona coluna last_lead_message_at em conversations para rastrear
o timestamp da ultima mensagem REAL enviada pelo lead (separado de
last_message_at que e atualizado por eventos internos como timeouts).
Usado pelo scheduler para verificar se o lead respondeu desde que um
job foi agendado (Feature 16).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c7d9e1f204"
down_revision: Union[str, None] = "2fe1aa3d570f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_lead_message_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        "ix_conversations_last_lead_message_at",
        "conversations",
        ["last_lead_message_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_last_lead_message_at", table_name="conversations")
    op.drop_column("conversations", "last_lead_message_at")
