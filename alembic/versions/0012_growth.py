"""add growth_records and development_milestones tables

Revision ID: 0012_growth
Revises: 0011_sleep
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_growth"
down_revision = "0011_sleep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── growth_records ─────────────────────────────────────────────────
    op.create_table(
        "growth_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("measured_at", sa.Date, nullable=False),
        sa.Column("height_cm", sa.Float, nullable=True),
        sa.Column("weight_kg", sa.Float, nullable=True),
        sa.Column("head_circumference_cm", sa.Float, nullable=True),
        sa.Column("bmi", sa.Float, nullable=True),
        sa.Column("age_months", sa.Integer, nullable=True),
        sa.Column("height_percentile", sa.Float, nullable=True),
        sa.Column("weight_percentile", sa.Float, nullable=True),
        sa.Column("bmi_percentile", sa.Float, nullable=True),
        sa.Column("height_zscore", sa.Float, nullable=True),
        sa.Column("weight_zscore", sa.Float, nullable=True),
        sa.Column("height_category", sa.String(30), nullable=True),
        sa.Column("weight_category", sa.String(30), nullable=True),
        sa.Column("bmi_category", sa.String(30), nullable=True),
        sa.Column("assessment", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_growth_records_member_id", "growth_records", ["member_id"])
    op.create_index("ix_growth_records_measured_at", "growth_records", ["measured_at"])

    # ── development_milestones ─────────────────────────────────────────
    op.create_table(
        "development_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestone_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("typical_age_start", sa.Integer, nullable=True),
        sa.Column("typical_age_end", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("achieved_at", sa.Date, nullable=True),
        sa.Column("achieved_age_months", sa.Integer, nullable=True),
        sa.Column("is_preset", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_development_milestones_member_id", "development_milestones", ["member_id"])
    op.create_index("ix_development_milestones_type", "development_milestones", ["milestone_type"])


def downgrade() -> None:
    op.drop_index("ix_development_milestones_type", "development_milestones")
    op.drop_index("ix_development_milestones_member_id", "development_milestones")
    op.drop_table("development_milestones")
    op.drop_index("ix_growth_records_measured_at", "growth_records")
    op.drop_index("ix_growth_records_member_id", "growth_records")
    op.drop_table("growth_records")
