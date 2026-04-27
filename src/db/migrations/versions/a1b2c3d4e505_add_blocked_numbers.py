"""add_blocked_numbers

Revision ID: a1b2c3d4e505
Revises: f8e2a1b3c407
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e505'
down_revision: Union[str, None] = 'f8e2a1b3c407'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS blocked_numbers (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            phone       VARCHAR(20) NOT NULL UNIQUE,
            reason      TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_blocked_numbers_phone ON blocked_numbers (phone)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS blocked_numbers")
