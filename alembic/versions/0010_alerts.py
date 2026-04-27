"""add health_thresholds, health_alerts, health_trend_snapshots tables

Revision ID: 0010_alerts
Revises: 0009_fitness
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_alerts"
down_revision = "0009_fitness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── health_thresholds ─────────────────────────────────────────────
    op.create_table(
        "health_thresholds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("warning_low", sa.Float, nullable=True),
        sa.Column("danger_low", sa.Float, nullable=True),
        sa.Column("warning_high", sa.Float, nullable=True),
        sa.Column("danger_high", sa.Float, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("member_id", "metric_type", name="uq_health_thresholds_member_metric"),
    )
    op.create_index("ix_health_thresholds_member_id", "health_thresholds", ["member_id"])

    # ── health_alerts ─────────────────────────────────────────────────
    op.create_table(
        "health_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("triggered_value", sa.Float, nullable=False),
        sa.Column("threshold_value", sa.Float, nullable=False),
        sa.Column("breach_direction", sa.String(10), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("llm_advice", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_health_alerts_member_triggered", "health_alerts", ["member_id", "triggered_at"])
    op.create_index("ix_health_alerts_status", "health_alerts", ["status"])

    # ── health_trend_snapshots ────────────────────────────────────────
    op.create_table(
        "health_trend_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("data_points", sa.Integer, nullable=False),
        sa.Column("mean_value", sa.Float, nullable=True),
        sa.Column("min_value", sa.Float, nullable=True),
        sa.Column("max_value", sa.Float, nullable=True),
        sa.Column("std_value", sa.Float, nullable=True),
        sa.Column("slope_per_day", sa.Float, nullable=True),
        sa.Column("trend_direction", sa.String(20), nullable=True),
        sa.Column("llm_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_health_trend_snapshots_member_metric", "health_trend_snapshots", ["member_id", "metric_type"])


def downgrade() -> None:
    op.drop_index("ix_health_trend_snapshots_member_metric", "health_trend_snapshots")
    op.drop_table("health_trend_snapshots")
    op.drop_index("ix_health_alerts_status", "health_alerts")
    op.drop_index("ix_health_alerts_member_triggered", "health_alerts")
    op.drop_table("health_alerts")
    op.drop_index("ix_health_thresholds_member_id", "health_thresholds")
    op.drop_table("health_thresholds")
