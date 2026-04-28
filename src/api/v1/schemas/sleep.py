"""睡眠质量分析 Schemas（T006）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SleepRecordCreate(BaseModel):
    sleep_start: datetime = Field(..., description="入睡时间（ISO 8601，含时区）")
    sleep_end: datetime = Field(..., description="起床时间（ISO 8601，含时区）")
    deep_sleep_minutes: Optional[int] = Field(None, ge=0, description="深睡眠时长（分钟）")
    light_sleep_minutes: Optional[int] = Field(None, ge=0, description="浅睡眠时长（分钟）")
    rem_minutes: Optional[int] = Field(None, ge=0, description="REM 时长（分钟）")
    awake_minutes: Optional[int] = Field(None, ge=0, description="夜间清醒时长（分钟）")
    interruptions: Optional[int] = Field(None, ge=0, description="夜间觉醒次数")
    spo2_min: Optional[float] = Field(None, ge=50, le=100, description="夜间最低血氧%")
    spo2_avg: Optional[float] = Field(None, ge=50, le=100, description="夜间平均血氧%")
    source: str = Field("manual", description="数据来源：manual / mi_band / apple_health / fitbit")
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_times(self) -> "SleepRecordCreate":
        if self.sleep_end <= self.sleep_start:
            raise ValueError("sleep_end 必须晚于 sleep_start")
        duration = int((self.sleep_end - self.sleep_start).total_seconds() / 60)
        if duration < 10 or duration > 1440:
            raise ValueError("睡眠时长须在 10 分钟到 24 小时之间")
        return self


class SleepRecordOut(BaseModel):
    id: UUID
    member_id: UUID
    sleep_start: datetime
    sleep_end: datetime
    total_minutes: int
    deep_sleep_minutes: Optional[int] = None
    light_sleep_minutes: Optional[int] = None
    rem_minutes: Optional[int] = None
    awake_minutes: Optional[int] = None
    interruptions: Optional[int] = None
    spo2_min: Optional[float] = None
    spo2_avg: Optional[float] = None
    sleep_score: Optional[int] = None
    quality: Optional[str] = None
    apnea_risk: Optional[str] = None
    source: str
    advice: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class SleepRecordList(BaseModel):
    total: int
    items: list[SleepRecordOut]


class SleepWeeklySummary(BaseModel):
    count: int
    avg_score: Optional[float] = None
    avg_hours: float
    poor_or_fair_count: int
    apnea_high_count: int
    min_spo2_overall: Optional[float] = None
    recent_scores: list[int]
