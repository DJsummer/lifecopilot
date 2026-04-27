"""add skin_analyses table

Revision ID: 0007_skin_analyses
Revises: 0006_mental_health
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_skin_analyses"
down_revision = "0006_mental_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skin_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("body_part", sa.String(100), nullable=True),
        sa.Column("user_description", sa.Text, nullable=True),
        sa.Column("result", sa.String(20), nullable=False, server_default="attention"),
        sa.Column("structured_analysis", sa.Text, nullable=True),
        sa.Column("llm_summary", sa.Text, nullable=True),
        sa.Column("audit_model", sa.String(100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_skin_analyses_member_id", "skin_analyses", ["member_id"])
    op.create_index("ix_skin_analyses_occurred_at", "skin_analyses", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_skin_analyses_occurred_at", "skin_analyses")
    op.drop_index("ix_skin_analyses_member_id", "skin_analyses")
    op.drop_table("skin_analyses")
