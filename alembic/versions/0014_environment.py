"""add environment_records and environment_advice tables

Revision ID: 0014_environment
Revises: 0013_fall_risk
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_environment"
down_revision = "0013_fall_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── environment_records ───────────────────────────────────────────
    op.create_table(
        "environment_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("family_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(100), nullable=True),
        sa.Column("device_type", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("location", sa.String(100), nullable=True),
        sa.Column("metric_type", sa.String(30), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_alert", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("alert_level", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_env_records_family_id",  "environment_records", ["family_id"])
    op.create_index("ix_env_records_metric_type", "environment_records", ["metric_type"])
    op.create_index("ix_env_records_measured_at", "environment_records", ["measured_at"])

    # ── environment_advice ────────────────────────────────────────────
    op.create_table(
        "environment_advice",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("family_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("air_quality_level", sa.String(20), nullable=False),
        sa.Column("pm2_5_value", sa.Float, nullable=True),
        sa.Column("co2_value", sa.Float, nullable=True),
        sa.Column("temperature_value", sa.Float, nullable=True),
        sa.Column("humidity_value", sa.Float, nullable=True),
        sa.Column("advice_text", sa.Text, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_env_advice_family_id",    "environment_advice", ["family_id"])
    op.create_index("ix_env_advice_generated_at", "environment_advice", ["generated_at"])


def downgrade() -> None:
    op.drop_table("environment_advice")
    op.drop_table("environment_records")
