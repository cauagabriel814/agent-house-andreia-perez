"""add_property_attributes

Revision ID: c1d2e3f4a507
Revises: b2c3d4e5f606
Create Date: 2026-04-30 00:00:00.000000

Converte aceita_permuta, aceita_financiamento e disponivel de Boolean para String,
e adiciona novos campos de atributos imobiliarios.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a507"
down_revision: Union[str, None] = "b2c3d4e5f606"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Converte colunas Boolean → VARCHAR com valor legivel
    op.drop_index("ix_properties_disponivel", table_name="properties")

    op.alter_column(
        "properties", "aceita_permuta",
        existing_type=sa.Boolean(),
        type_=sa.String(length=50),
        existing_nullable=False,
        nullable=True,
        postgresql_using="CASE WHEN aceita_permuta THEN 'Sim' ELSE 'Não' END",
    )
    op.alter_column(
        "properties", "aceita_financiamento",
        existing_type=sa.Boolean(),
        type_=sa.String(length=50),
        existing_nullable=False,
        nullable=True,
        postgresql_using="CASE WHEN aceita_financiamento THEN 'Sim' ELSE 'Não' END",
    )
    op.alter_column(
        "properties", "disponivel",
        existing_type=sa.Boolean(),
        type_=sa.String(length=50),
        existing_nullable=False,
        nullable=True,
        postgresql_using="CASE WHEN disponivel THEN 'Sim' ELSE 'Não' END",
    )

    op.create_index("ix_properties_disponivel", "properties", ["disponivel"], unique=False)

    # Novos campos de categoria com multiplas opcoes
    op.add_column("properties", sa.Column("mobiliado", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("ocupacao", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("vista", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("estado_conservacao", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("escritura", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("piscina", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("churrasqueira", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("tipo_piso", sa.String(length=50), nullable=True))

    # Amenidades booleanas
    op.add_column("properties", sa.Column("suite_master", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("closet", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("varanda_gourmet", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("sauna", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("elevador_privativo", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("sala_estar", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("sala_jantar", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("lavabo", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("deposito", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Remove novos campos
    for col in (
        "deposito", "lavabo", "sala_jantar", "sala_estar", "elevador_privativo",
        "sauna", "varanda_gourmet", "closet", "suite_master",
        "tipo_piso", "churrasqueira", "piscina", "escritura",
        "estado_conservacao", "vista", "ocupacao", "mobiliado",
    ):
        op.drop_column("properties", col)

    op.drop_index("ix_properties_disponivel", table_name="properties")

    op.alter_column(
        "properties", "disponivel",
        existing_type=sa.String(length=50),
        type_=sa.Boolean(),
        existing_nullable=True,
        nullable=False,
        postgresql_using="disponivel ILIKE 'Sim'",
    )
    op.alter_column(
        "properties", "aceita_financiamento",
        existing_type=sa.String(length=50),
        type_=sa.Boolean(),
        existing_nullable=True,
        nullable=False,
        postgresql_using="aceita_financiamento ILIKE 'Sim'",
    )
    op.alter_column(
        "properties", "aceita_permuta",
        existing_type=sa.String(length=50),
        type_=sa.Boolean(),
        existing_nullable=True,
        nullable=False,
        postgresql_using="aceita_permuta ILIKE 'Sim'",
    )

    op.create_index("ix_properties_disponivel", "properties", ["disponivel"], unique=False)
