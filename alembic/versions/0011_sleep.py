"""add sleep_records table

Revision ID: 0011_sleep
Revises: 0010_alerts
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_sleep"
down_revision = "0010_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sleep_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sleep_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sleep_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_minutes", sa.Integer, nullable=False),
        sa.Column("deep_sleep_minutes", sa.Integer, nullable=True),
        sa.Column("light_sleep_minutes", sa.Integer, nullable=True),
        sa.Column("rem_minutes", sa.Integer, nullable=True),
        sa.Column("awake_minutes", sa.Integer, nullable=True),
        sa.Column("interruptions", sa.Integer, nullable=True),
        sa.Column("spo2_min", sa.Float, nullable=True),
        sa.Column("spo2_avg", sa.Float, nullable=True),
        sa.Column("sleep_score", sa.Integer, nullable=True),
        sa.Column("quality", sa.String(20), nullable=True),
        sa.Column("apnea_risk", sa.String(20), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("advice", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sleep_records_member_id", "sleep_records", ["member_id"])
    op.create_index("ix_sleep_records_sleep_start", "sleep_records", ["sleep_start"])


def downgrade() -> None:
    op.drop_index("ix_sleep_records_sleep_start", "sleep_records")
    op.drop_index("ix_sleep_records_member_id", "sleep_records")
    op.drop_table("sleep_records")
