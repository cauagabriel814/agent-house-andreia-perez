"""migrate_ids_to_uuid

Revision ID: d5f2a3b4c601
Revises: c4e8f2a1d305
Create Date: 2026-04-08 21:00:00.000000

Migra TODAS as PKs e FKs de INTEGER sequencial para UUID nativo do
PostgreSQL (gen_random_uuid via extensao pgcrypto).

ATENCAO: esta migration APAGA todos os dados existentes (drop_all)
e recria o schema a partir dos models atualizados. So deve ser usada
em ambientes de desenvolvimento/pre-producao.
"""

from typing import Sequence, Union

from alembic import op

from src.db.models import Base

revision: str = "d5f2a3b4c601"
down_revision: Union[str, None] = "c4e8f2a1d305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Habilitar extensao pgcrypto (necessaria para gen_random_uuid)
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # 2. Dropar todas as tabelas na ordem correta (filhos antes de pais)
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS scheduled_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS lead_scores CASCADE")
    op.execute("DROP TABLE IF EXISTS lead_tags CASCADE")
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS leads CASCADE")

    # Dropar tabela interna do Alembic para forcar recriacao limpa
    # (nao necessario; mantemos o historico de versoes)

    # 3. Recriar todas as tabelas a partir dos models (com UUID)
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Downgrade: volta para INTEGER. Como os dados foram apagados no
    # upgrade, o downgrade tambem e destrutivo.
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS scheduled_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS lead_scores CASCADE")
    op.execute("DROP TABLE IF EXISTS lead_tags CASCADE")
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS leads CASCADE")
    # Nota: para recriar com INTEGER, rode as migrations anteriores
    # (alembic downgrade c4e8f2a1d305 + alembic upgrade c4e8f2a1d305)
