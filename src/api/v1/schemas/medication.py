"""Pydantic schemas for medication management endpoints (T020)"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── 用药方案 ──────────────────────────────────────────────────────────

class MedicationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="药品名称")
    generic_name: Optional[str] = Field(None, max_length=200, description="通用名/成分名")
    dosage: str = Field(..., min_length=1, max_length=100, description="剂量，如 5mg")
    frequency: str = Field(..., min_length=1, max_length=100, description="频次，如 每日两次")
    instructions: Optional[str] = Field(None, description="服药注意事项")
    start_date: date = Field(..., description="开始日期")
    end_date: Optional[date] = Field(None, description="结束日期（长期用药可为空）")
    reminder_times: List[str] = Field(
        default_factory=list,
        description="提醒时间列表，格式 HH:MM，如 ['08:00', '20:00']",
    )

    @field_validator("reminder_times")
    @classmethod
    def validate_reminder_times(cls, v: List[str]) -> List[str]:
        import re
        for t in v:
            if not re.match(r"^\d{2}:\d{2}$", t):
                raise ValueError(f"提醒时间格式错误：{t}，应为 HH:MM")
        return v


class MedicationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    generic_name: Optional[str] = Field(None, max_length=200)
    dosage: Optional[str] = Field(None, min_length=1, max_length=100)
    frequency: Optional[str] = Field(None, min_length=1, max_length=100)
    instructions: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = Field(None, description="active / paused / completed")


class ReminderResponse(BaseModel):
    id: uuid.UUID
    remind_time: str
    is_active: bool

    class Config:
        from_attributes = True


class MedicationResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    name: str
    generic_name: Optional[str] = None
    dosage: str
    frequency: str
    instructions: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    status: str
    llm_description: Optional[str] = None
    reminders: List[ReminderResponse] = Field(default_factory=list)
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# ── 依从性记录 ────────────────────────────────────────────────────────

class AdherenceLogCreate(BaseModel):
    scheduled_at: datetime = Field(..., description="计划服药时间")
    actual_at: Optional[datetime] = Field(None, description="实际服药时间")
    status: str = Field(..., description="taken / missed / delayed / skipped")
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"taken", "missed", "delayed", "skipped"}
        if v not in allowed:
            raise ValueError(f"status 必须是 {allowed} 之一")
        return v


class AdherenceLogResponse(BaseModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    scheduled_at: datetime
    actual_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    delay_minutes: Optional[int] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AdherenceStatsResponse(BaseModel):
    """依从性统计摘要"""
    medication_id: uuid.UUID
    total_logs: int
    taken: int
    missed: int
    delayed: int
    skipped: int
    adherence_rate: float = Field(..., description="按时服药率（taken / total）")


# ── 药物相互作用 ──────────────────────────────────────────────────────

class InteractionCheckRequest(BaseModel):
    medication_names: List[str] = Field(
        ..., min_length=2, description="至少 2 种药品名称"
    )


class InteractionCheckResponse(BaseModel):
    medications: List[str]
    has_interaction: bool
    risk_level: str = Field(..., description="none / low / moderate / high / critical")
    interactions: List[dict] = Field(default_factory=list)
    summary: str
    advice: str
    disclaimer: str
