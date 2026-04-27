"""add nutrition tables

Revision ID: 0008_nutrition
Revises: 0007_skin_analyses
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_nutrition"
down_revision = "0007_skin_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── food_items ────────────────────────────────────────────────────
    op.create_table(
        "food_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("calories", sa.Float, nullable=True),
        sa.Column("protein", sa.Float, nullable=True),
        sa.Column("fat", sa.Float, nullable=True),
        sa.Column("carbohydrate", sa.Float, nullable=True),
        sa.Column("fiber", sa.Float, nullable=True),
        sa.Column("sodium", sa.Float, nullable=True),
        sa.Column("sugar", sa.Float, nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="builtin"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_food_items_name", "food_items", ["name"])

    # ── nutrition_goals ───────────────────────────────────────────────
    op.create_table(
        "nutrition_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("diet_type", sa.String(30), nullable=False, server_default="normal"),
        sa.Column("allergies", sa.Text, nullable=True),
        sa.Column("dietary_restrictions", sa.Text, nullable=True),
        sa.Column("daily_calories", sa.Float, nullable=True),
        sa.Column("daily_protein", sa.Float, nullable=True),
        sa.Column("daily_fat", sa.Float, nullable=True),
        sa.Column("daily_carbohydrate", sa.Float, nullable=True),
        sa.Column("daily_fiber", sa.Float, nullable=True),
        sa.Column("daily_sodium", sa.Float, nullable=True),
        sa.Column("llm_rationale", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── meal_plans ────────────────────────────────────────────────────
    op.create_table(
        "meal_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("nutrition_goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nutrition_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("plan_data", sa.Text, nullable=True),
        sa.Column("llm_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_meal_plans_member_week", "meal_plans", ["member_id", "week_start"])

    # ── diet_logs ─────────────────────────────────────────────────────
    op.create_table(
        "diet_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_date", sa.Date, nullable=False),
        sa.Column("meal_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("estimated_calories", sa.Float, nullable=True),
        sa.Column("estimated_protein", sa.Float, nullable=True),
        sa.Column("estimated_fat", sa.Float, nullable=True),
        sa.Column("estimated_carbohydrate", sa.Float, nullable=True),
        sa.Column("llm_feedback", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_diet_logs_member_date", "diet_logs", ["member_id", "log_date"])


def downgrade() -> None:
    op.drop_index("ix_diet_logs_member_date", "diet_logs")
    op.drop_table("diet_logs")
    op.drop_index("ix_meal_plans_member_week", "meal_plans")
    op.drop_table("meal_plans")
    op.drop_table("nutrition_goals")
    op.drop_index("ix_food_items_name", "food_items")
    op.drop_table("food_items")
