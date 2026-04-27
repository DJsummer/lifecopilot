"""营养规划 Schemas（T014）"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.models.nutrition import DietType, MealType


# ── 食物搜索 ─────────────────────────────────────────────────────────

class FoodItemOut(BaseModel):
    id: UUID
    name: str
    name_en: Optional[str]
    category: Optional[str]
    calories: Optional[float]
    protein: Optional[float]
    fat: Optional[float]
    carbohydrate: Optional[float]
    fiber: Optional[float]
    sodium: Optional[float]
    sugar: Optional[float]
    source: str
    model_config = {"from_attributes": True}


class FoodSearchResult(BaseModel):
    total: int
    items: List[FoodItemOut]


# ── 营养目标 ─────────────────────────────────────────────────────────

class NutritionGoalCreate(BaseModel):
    diet_type: DietType = DietType.NORMAL
    allergies: List[str] = Field(default_factory=list)
    dietary_restrictions: List[str] = Field(default_factory=list)


class NutritionGoalOut(BaseModel):
    id: UUID
    member_id: UUID
    diet_type: str
    allergies: Optional[List[str]] = None
    dietary_restrictions: Optional[List[str]] = None
    daily_calories: Optional[float]
    daily_protein: Optional[float]
    daily_fat: Optional[float]
    daily_carbohydrate: Optional[float]
    daily_fiber: Optional[float]
    daily_sodium: Optional[float]
    llm_rationale: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("allergies", "dietary_restrictions", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v


# ── 每周食谱 ─────────────────────────────────────────────────────────

class MealPlanOut(BaseModel):
    id: UUID
    member_id: UUID
    week_start: date
    week_end: date
    plan_data: Optional[List[Dict[str, Any]]] = None
    llm_summary: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("plan_data", mode="before")
    @classmethod
    def parse_plan(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v


class MealPlanList(BaseModel):
    total: int
    items: List[MealPlanOut]


# ── 饮食日志 ─────────────────────────────────────────────────────────

class DietLogCreate(BaseModel):
    log_date: date
    meal_type: MealType
    description: str = Field(..., min_length=2, max_length=1000)


class DietLogOut(BaseModel):
    id: UUID
    member_id: UUID
    log_date: date
    meal_type: str
    description: str
    estimated_calories: Optional[float]
    estimated_protein: Optional[float]
    estimated_fat: Optional[float]
    estimated_carbohydrate: Optional[float]
    llm_feedback: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class DietLogList(BaseModel):
    total: int
    items: List[DietLogOut]


# ── 日摄入汇总 ───────────────────────────────────────────────────────

class DailyIntakeSummary(BaseModel):
    log_date: date
    total_calories: Optional[float]
    total_protein: Optional[float]
    total_fat: Optional[float]
    total_carbohydrate: Optional[float]
    meal_count: int
