"""add_kommo_ids_to_leads

Revision ID: c4e8f2a1d305
Revises: b3c7d9e1f204
Create Date: 2026-04-02 00:00:00.000000

Adiciona colunas kommo_contact_id e kommo_lead_id em leads para
rastrear os IDs dos registros criados no KOMMO CRM, evitando
duplicatas entre sessoes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8f2a1d305"
down_revision: Union[str, None] = "b3c7d9e1f204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("kommo_contact_id", sa.String(50), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("kommo_lead_id", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "kommo_lead_id")
    op.drop_column("leads", "kommo_contact_id")
