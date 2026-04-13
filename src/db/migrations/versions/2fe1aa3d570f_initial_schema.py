"""initial_schema

Revision ID: 2fe1aa3d570f
Revises:
Create Date: 2026-03-23 10:29:25.807644

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2fe1aa3d570f"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- leads ---
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("origin", sa.String(100), nullable=True),
        sa.Column("utm_source", sa.String(255), nullable=True),
        sa.Column("classification", sa.String(20), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("ix_leads_phone", "leads", ["phone"], unique=True)

    # --- conversations ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("current_node", sa.String(100), nullable=True),
        sa.Column("graph_state", postgresql.JSONB(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_notified", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"])
    op.create_index("ix_conversations_lead_status", "conversations", ["lead_id", "status"])

    # --- messages ---
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("processed_content", sa.Text(), nullable=True),
        sa.Column("media_url", sa.String(500), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_lead_id", "messages", ["lead_id"])

    # --- lead_tags ---
    op.create_table(
        "lead_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("tag_name", sa.String(100), nullable=False),
        sa.Column("tag_value", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lead_tags_lead_id", "lead_tags", ["lead_id"])
    op.create_index("ix_lead_tags_tag_name", "lead_tags", ["tag_name"])
    op.create_index("ix_lead_tags_lead_name", "lead_tags", ["lead_id", "tag_name"])

    # --- lead_scores ---
    op.create_table(
        "lead_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("score_type", sa.String(20), nullable=False),
        sa.Column("investimento_pts", sa.Integer(), server_default="0"),
        sa.Column("pagamento_pts", sa.Integer(), server_default="0"),
        sa.Column("urgencia_pts", sa.Integer(), server_default="0"),
        sa.Column("situacao_pts", sa.Integer(), server_default="0"),
        sa.Column("dados_pts", sa.Integer(), server_default="0"),
        sa.Column("total_score", sa.Integer(), server_default="0"),
        sa.Column("classification", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lead_scores_lead_id", "lead_scores", ["lead_id"])
    op.create_index("ix_lead_scores_lead_type", "lead_scores", ["lead_id", "score_type"])

    # --- scheduled_jobs ---
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scheduled_jobs_lead_id", "scheduled_jobs", ["lead_id"])
    op.create_index("ix_scheduled_jobs_status", "scheduled_jobs", ["status"])
    op.create_index("ix_scheduled_jobs_pending", "scheduled_jobs", ["status", "scheduled_for"])

    # --- notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_lead_id", "notifications", ["lead_id"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("scheduled_jobs")
    op.drop_table("lead_scores")
    op.drop_table("lead_tags")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("leads")
