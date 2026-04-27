"""运动方案 Schemas（T015）"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.models.exercise import ExerciseGoal, ExerciseType, FitnessLevel, WorkoutLogStatus


# ══════════════════════════════════════════════════════════════════════
# 体能评估问卷
# ══════════════════════════════════════════════════════════════════════

class FitnessAssessmentCreate(BaseModel):
    fitness_level: FitnessLevel = FitnessLevel.BEGINNER
    primary_goal: ExerciseGoal = ExerciseGoal.MAINTAIN_HEALTH
    available_minutes_per_session: int = Field(30, ge=10, le=240)
    available_days_per_week: int = Field(3, ge=1, le=7)
    preferred_types: List[ExerciseType] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    equipment: List[str] = Field(default_factory=list)


class FitnessAssessmentOut(BaseModel):
    id: UUID
    member_id: UUID
    fitness_level: str
    primary_goal: str
    available_minutes_per_session: int
    available_days_per_week: int
    preferred_types: Optional[List[str]] = None
    limitations: Optional[List[str]] = None
    equipment: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("preferred_types", "limitations", "equipment", mode="before")
    @classmethod
    def _parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v


# ══════════════════════════════════════════════════════════════════════
# 运动计划
# ══════════════════════════════════════════════════════════════════════

class ExercisePlanCreate(BaseModel):
    week_start: Optional[date] = None   # 不传则默认本周一


class ExercisePlanOut(BaseModel):
    id: UUID
    member_id: UUID
    fitness_assessment_id: UUID
    week_start: date
    week_end: date
    plan_data: Optional[Any] = None
    llm_summary: Optional[str] = None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("plan_data", mode="before")
    @classmethod
    def _parse_plan(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v


class ExercisePlanList(BaseModel):
    total: int
    items: List[ExercisePlanOut]


# ══════════════════════════════════════════════════════════════════════
# 运动日志
# ══════════════════════════════════════════════════════════════════════

class WorkoutLogCreate(BaseModel):
    log_date: date
    exercise_type: ExerciseType
    exercise_name: str = Field(..., max_length=200)
    duration_minutes: Optional[int] = Field(None, ge=1, le=600)
    avg_heart_rate: Optional[int] = Field(None, ge=30, le=250)
    max_heart_rate: Optional[int] = Field(None, ge=30, le=250)
    status: WorkoutLogStatus = WorkoutLogStatus.COMPLETED
    notes: Optional[str] = None
    exercise_plan_id: Optional[UUID] = None


class WorkoutLogOut(BaseModel):
    id: UUID
    member_id: UUID
    exercise_plan_id: Optional[UUID] = None
    log_date: date
    exercise_type: str
    exercise_name: str
    duration_minutes: Optional[int] = None
    calories_burned: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    status: str
    notes: Optional[str] = None
    llm_feedback: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class WorkoutLogList(BaseModel):
    total: int
    items: List[WorkoutLogOut]


# ══════════════════════════════════════════════════════════════════════
# 每周汇总
# ══════════════════════════════════════════════════════════════════════

class WeeklySummary(BaseModel):
    week_start: str
    week_end: str
    total_sessions: int
    completed_sessions: int
    total_minutes: int
    total_calories: float
    avg_heart_rate: Optional[int] = None
