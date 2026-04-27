"""add fitness tables

Revision ID: 0009_fitness
Revises: 0008_nutrition
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_fitness"
down_revision = "0008_nutrition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fitness_assessments ───────────────────────────────────────────
    op.create_table(
        "fitness_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("fitness_level", sa.String(20), nullable=False, server_default="beginner"),
        sa.Column("primary_goal", sa.String(30), nullable=False, server_default="maintain_health"),
        sa.Column("available_minutes_per_session", sa.Integer, nullable=False, server_default="30"),
        sa.Column("available_days_per_week", sa.Integer, nullable=False, server_default="3"),
        sa.Column("preferred_types", sa.Text, nullable=True),
        sa.Column("limitations", sa.Text, nullable=True),
        sa.Column("equipment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_fitness_assessments_member_id", "fitness_assessments", ["member_id"])

    # ── exercise_plans ────────────────────────────────────────────────
    op.create_table(
        "exercise_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("fitness_assessment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fitness_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("plan_data", sa.Text, nullable=True),
        sa.Column("llm_summary", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_exercise_plans_member_week", "exercise_plans", ["member_id", "week_start"])

    # ── workout_logs ──────────────────────────────────────────────────
    op.create_table(
        "workout_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("exercise_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("log_date", sa.Date, nullable=False),
        sa.Column("exercise_type", sa.String(20), nullable=False),
        sa.Column("exercise_name", sa.String(200), nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=True),
        sa.Column("calories_burned", sa.Float, nullable=True),
        sa.Column("avg_heart_rate", sa.Integer, nullable=True),
        sa.Column("max_heart_rate", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("llm_feedback", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workout_logs_member_date", "workout_logs", ["member_id", "log_date"])


def downgrade() -> None:
    op.drop_index("ix_workout_logs_member_date", "workout_logs")
    op.drop_table("workout_logs")
    op.drop_index("ix_exercise_plans_member_week", "exercise_plans")
    op.drop_table("exercise_plans")
    op.drop_index("ix_fitness_assessments_member_id", "fitness_assessments")
    op.drop_table("fitness_assessments")
