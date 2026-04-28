"""add fall_risk_assessments and inactivity_logs tables

Revision ID: 0013_fall_risk
Revises: 0012_growth
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_fall_risk"
down_revision = "0012_growth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fall_risk_assessments ─────────────────────────────────────────
    op.create_table(
        "fall_risk_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_fall_history", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_osteoporosis", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_neurological_disease", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("uses_sedatives", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_gait_disorder", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("uses_walking_aid", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_vision_impairment", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_weakness_or_balance_issue", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("lives_alone", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("frequent_nocturia", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_urge_incontinence", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("age_at_assessment", sa.Integer, nullable=True),
        sa.Column("total_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("recommendations", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_fall_risk_assessments_member_id", "fall_risk_assessments", ["member_id"])
    op.create_index("ix_fall_risk_assessments_assessed_at", "fall_risk_assessments", ["assessed_at"])

    # ── inactivity_logs ───────────────────────────────────────────────
    op.create_table(
        "inactivity_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_hours", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("alert_sent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("alert_contact", sa.String(200), nullable=True),
        sa.Column("alert_message", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_inactivity_logs_member_id", "inactivity_logs", ["member_id"])
    op.create_index("ix_inactivity_logs_period_start", "inactivity_logs", ["period_start"])


def downgrade() -> None:
    op.drop_index("ix_inactivity_logs_period_start", "inactivity_logs")
    op.drop_index("ix_inactivity_logs_member_id", "inactivity_logs")
    op.drop_table("inactivity_logs")
    op.drop_index("ix_fall_risk_assessments_assessed_at", "fall_risk_assessments")
    op.drop_index("ix_fall_risk_assessments_member_id", "fall_risk_assessments")
    op.drop_table("fall_risk_assessments")
