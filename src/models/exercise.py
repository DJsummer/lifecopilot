"""运动方案与追踪模型（T015）"""
import uuid
from typing import Optional
from datetime import date
from enum import Enum

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


# ── 枚举定义 ────────────────────────────────────────────────────────────

class FitnessLevel(str, Enum):
    SEDENTARY = "sedentary"        # 久坐不动
    BEGINNER = "beginner"          # 初级（每周运动 <1 次）
    INTERMEDIATE = "intermediate"  # 中级（每周 1-3 次）
    ADVANCED = "advanced"          # 高级（每周 3-5 次）
    ATHLETE = "athlete"            # 专业（每日训练）


class ExerciseGoal(str, Enum):
    LOSE_WEIGHT = "lose_weight"          # 减脂
    BUILD_MUSCLE = "build_muscle"        # 增肌
    IMPROVE_CARDIO = "improve_cardio"    # 提升心肺
    MAINTAIN_HEALTH = "maintain_health"  # 维持健康
    REHABILITATION = "rehabilitation"    # 康复训练
    FLEXIBILITY = "flexibility"          # 柔韧性提升


class ExerciseType(str, Enum):
    CARDIO = "cardio"            # 有氧（跑步/游泳/骑车）
    STRENGTH = "strength"        # 力量（哑铃/自重训练）
    FLEXIBILITY = "flexibility"  # 柔韧（瑜伽/拉伸）
    HIIT = "hiit"                # 高强度间歇
    SPORTS = "sports"            # 球类/团队运动
    WALKING = "walking"          # 健步走（老人/康复友好）
    SWIMMING = "swimming"        # 游泳


class WorkoutLogStatus(str, Enum):
    COMPLETED = "completed"  # 已完成
    SKIPPED = "skipped"      # 跳过
    PARTIAL = "partial"      # 部分完成


# ── 体能评估问卷 ────────────────────────────────────────────────────────

class FitnessAssessment(BaseModel):
    """体能评估问卷（T015 前置步骤）"""
    __tablename__ = "fitness_assessments"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    fitness_level: Mapped[FitnessLevel] = mapped_column(
        String(20), nullable=False, default=FitnessLevel.BEGINNER
    )
    primary_goal: Mapped[ExerciseGoal] = mapped_column(
        String(30), nullable=False, default=ExerciseGoal.MAINTAIN_HEALTH
    )
    # 可用于运动的时间（分钟/每次）
    available_minutes_per_session: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # 每周可运动天数
    available_days_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # 偏好运动类型 JSON 数组
    preferred_types: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 受伤/禁忌 JSON 数组（如 ["膝关节损伤", "腰椎间盘突出"]）
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 有无可用器材 JSON 数组（如 ["哑铃", "弹力带"]，空=无器材/仅自重）
    equipment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="fitness_assessment")
    exercise_plans: Mapped[list["ExercisePlan"]] = relationship(
        back_populates="fitness_assessment", cascade="all, delete-orphan"
    )


# ── 运动计划 ────────────────────────────────────────────────────────────

class ExercisePlan(BaseModel):
    """LLM 生成的个性化运动计划"""
    __tablename__ = "exercise_plans"

    fitness_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fitness_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    # LLM 生成的 7 天运动计划 JSON
    # [{day:"周一", rest:false, exercises:[{name,type,sets,reps,duration_min,calories_est,tips}]}]
    plan_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM 整体说明（目标/注意事项/渐进建议）
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    fitness_assessment: Mapped["FitnessAssessment"] = relationship(back_populates="exercise_plans")
    member: Mapped["Member"] = relationship(back_populates="exercise_plans")
    workout_logs: Mapped[list["WorkoutLog"]] = relationship(
        back_populates="exercise_plan", cascade="all, delete-orphan"
    )


# ── 运动记录日志 ────────────────────────────────────────────────────────

class WorkoutLog(BaseModel):
    """运动执行记录"""
    __tablename__ = "workout_logs"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    exercise_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercise_plans.id", ondelete="SET NULL"), nullable=True
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    exercise_type: Mapped[ExerciseType] = mapped_column(String(20), nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calories_burned: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 心率数据（可选，来自可穿戴设备）
    avg_heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[WorkoutLogStatus] = mapped_column(
        String(20), nullable=False, default=WorkoutLogStatus.COMPLETED
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM 基于当次运动给出的反馈与建议
    llm_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="workout_logs")
    exercise_plan: Mapped[Optional["ExercisePlan"]] = relationship(back_populates="workout_logs")


from src.models.member import Member  # noqa: E402
