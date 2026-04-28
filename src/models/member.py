"""家庭账户与成员模型"""
import uuid
from typing import Optional
from datetime import date
from enum import Enum

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class MemberRole(str, Enum):
    ADMIN = "admin"      # 家庭管理员（创建者）
    ADULT = "adult"      # 成人
    ELDER = "elder"      # 老人（特殊健康关注）
    CHILD = "child"      # 儿童（生长发育追踪）


class Family(BaseModel):
    """家庭账户"""
    __tablename__ = "families"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)

    members: Mapped[list["Member"]] = relationship(back_populates="family", cascade="all, delete-orphan")


class Member(BaseModel):
    """家庭成员"""
    __tablename__ = "members"

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[MemberRole] = mapped_column(String(20), nullable=False, default=MemberRole.ADULT)
    gender: Mapped[Optional[Gender]] = mapped_column(String(10), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 认证（可选，儿童/老人可不登录）
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, nullable=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    family: Mapped["Family"] = relationship(back_populates="members")
    health_records: Mapped[list["HealthRecord"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    medications: Mapped[list["Medication"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    symptom_logs: Mapped[list["SymptomLog"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    lab_reports: Mapped[list["LabReport"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    health_reports: Mapped[list["HealthReport"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    visit_summaries: Mapped[list["VisitSummary"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    mental_health_logs: Mapped[list["MentalHealthLog"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    skin_analyses: Mapped[list["SkinAnalysis"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    nutrition_goal: Mapped[Optional["NutritionGoal"]] = relationship(back_populates="member", uselist=False, cascade="all, delete-orphan")
    meal_plans: Mapped[list["MealPlan"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    diet_logs: Mapped[list["DietLog"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    fitness_assessment: Mapped[Optional["FitnessAssessment"]] = relationship(back_populates="member", uselist=False, cascade="all, delete-orphan")
    exercise_plans: Mapped[list["ExercisePlan"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    workout_logs: Mapped[list["WorkoutLog"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    health_thresholds: Mapped[list["HealthThreshold"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    health_alerts: Mapped[list["HealthAlert"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    health_trend_snapshots: Mapped[list["HealthTrendSnapshot"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    sleep_records: Mapped[list["SleepRecord"]] = relationship(back_populates="member", cascade="all, delete-orphan")


# 避免循环导入，延迟引用
from src.models.health import HealthRecord, SymptomLog  # noqa: E402
from src.models.medication import Medication  # noqa: E402
from src.models.report import LabReport, HealthReport  # noqa: E402
from src.models.visit import VisitSummary  # noqa: E402
from src.models.mental_health import MentalHealthLog  # noqa: E402
from src.models.skin_analysis import SkinAnalysis  # noqa: E402
from src.models.nutrition import NutritionGoal, MealPlan, DietLog  # noqa: E402
from src.models.exercise import FitnessAssessment, ExercisePlan, WorkoutLog  # noqa: E402
from src.models.health_alert import HealthThreshold, HealthAlert, HealthTrendSnapshot  # noqa: E402
from src.models.sleep import SleepRecord  # noqa: E402
