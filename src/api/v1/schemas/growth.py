"""儿童生长发育评估 Schemas（T007）"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class GrowthRecordCreate(BaseModel):
    measured_at: date = Field(..., description="测量日期")
    height_cm: Optional[float] = Field(None, gt=20, lt=250, description="身高（cm）")
    weight_kg: Optional[float] = Field(None, gt=0.5, lt=200, description="体重（kg）")
    head_circumference_cm: Optional[float] = Field(None, gt=20, lt=70, description="头围（cm）")
    notes: Optional[str] = None

    @model_validator(mode="after")
    def at_least_one_measurement(self) -> "GrowthRecordCreate":
        if self.height_cm is None and self.weight_kg is None and self.head_circumference_cm is None:
            raise ValueError("至少填写一项测量值（身高/体重/头围）")
        return self


class GrowthRecordOut(BaseModel):
    id: UUID
    member_id: UUID
    measured_at: date
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    head_circumference_cm: Optional[float] = None
    bmi: Optional[float] = None
    age_months: Optional[int] = None
    height_percentile: Optional[float] = None
    weight_percentile: Optional[float] = None
    bmi_percentile: Optional[float] = None
    height_zscore: Optional[float] = None
    weight_zscore: Optional[float] = None
    height_category: Optional[str] = None
    weight_category: Optional[str] = None
    bmi_category: Optional[str] = None
    assessment: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class GrowthRecordList(BaseModel):
    total: int
    items: list[GrowthRecordOut]


class MilestoneCreate(BaseModel):
    milestone_type: str = Field(..., description="motor/fine_motor/language/cognitive/social")
    title: str = Field(..., min_length=1, max_length=200)
    typical_age_start: Optional[int] = Field(None, ge=0, le=120, description="典型达成月龄下限")
    typical_age_end: Optional[int] = Field(None, ge=0, le=120, description="典型达成月龄上限")
    notes: Optional[str] = None


class MilestoneAchieve(BaseModel):
    achieved_at: date
    notes: Optional[str] = None


class MilestoneOut(BaseModel):
    id: UUID
    member_id: UUID
    milestone_type: str
    title: str
    typical_age_start: Optional[int] = None
    typical_age_end: Optional[int] = None
    status: str
    achieved_at: Optional[date] = None
    achieved_age_months: Optional[int] = None
    is_preset: bool
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class MilestoneList(BaseModel):
    total: int
    items: list[MilestoneOut]


class GrowthSummary(BaseModel):
    """最近一次测量 + 各项趋势摘要"""
    record_count: int
    latest_record: Optional[GrowthRecordOut] = None
    milestone_total: int
    milestone_achieved: int
    milestone_delayed: int
