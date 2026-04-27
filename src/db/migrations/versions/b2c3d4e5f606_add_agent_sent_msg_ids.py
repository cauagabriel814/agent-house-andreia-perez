"""add_agent_sent_msg_ids

Revision ID: b2c3d4e5f606
Revises: a1b2c3d4e505
Create Date: 2026-04-27 00:00:00.000000

Tabela leve para rastrear IDs de mensagens enviadas pelo agente via API.
Usada para distinguir mensagens do agente vs intervencao humana no webhook fromMe.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b2c3d4e5f606'
down_revision: Union[str, None] = 'a1b2c3d4e505'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_sent_msg_ids (
            msg_id      VARCHAR(100) PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_sent_msg_ids_created_at "
        "ON agent_sent_msg_ids (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_sent_msg_ids")
