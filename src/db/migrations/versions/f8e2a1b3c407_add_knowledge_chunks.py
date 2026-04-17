"""add_knowledge_chunks

Revision ID: f8e2a1b3c407
Revises: 5bb9d83748f6
Create Date: 2026-04-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f8e2a1b3c407'
down_revision: Union[str, None] = '5bb9d83748f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Habilita extensão pgvector (necessária para o tipo vector)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Cria tabela de chunks da knowledge base com embedding vetorial (1536 dims = text-embedding-3-small)
    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content     TEXT NOT NULL,
            embedding   vector(1536),
            source      VARCHAR(255) NOT NULL DEFAULT 'manual',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_chunks")
