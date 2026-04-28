"""老人跌倒风险评估 Schemas（T008）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FallRiskAssessmentCreate(BaseModel):
    assessed_at: datetime = Field(..., description="评估时间（ISO 8601，含时区）")

    # 病史类
    has_fall_history: bool = Field(False, description="近3个月内有跌倒史 (+3)")
    has_osteoporosis: bool = Field(False, description="骨质疏松症 (+2)")
    has_neurological_disease: bool = Field(False, description="帕金森/神经系统疾病 (+3)")
    uses_sedatives: bool = Field(False, description="使用镇静剂/催眠药/抗抑郁药 (+2)")

    # 功能类
    has_gait_disorder: bool = Field(False, description="步态异常 (+3)")
    uses_walking_aid: bool = Field(False, description="需助行器/手杖 (+2)")
    has_vision_impairment: bool = Field(False, description="视力下降（未矫正） (+2)")
    has_weakness_or_balance_issue: bool = Field(False, description="肌力下降/平衡感差 (+3)")

    # 环境/行为类
    lives_alone: bool = Field(False, description="独居 (+2)")
    frequent_nocturia: bool = Field(False, description="夜间如厕频繁（≥2次/夜） (+2)")
    has_urge_incontinence: bool = Field(False, description="急迫性尿失禁 (+2)")

    notes: Optional[str] = None


class FallRiskAssessmentOut(BaseModel):
    id: UUID
    member_id: UUID
    assessed_at: datetime
    has_fall_history: bool
    has_osteoporosis: bool
    has_neurological_disease: bool
    uses_sedatives: bool
    has_gait_disorder: bool
    uses_walking_aid: bool
    has_vision_impairment: bool
    has_weakness_or_balance_issue: bool
    lives_alone: bool
    frequent_nocturia: bool
    has_urge_incontinence: bool
    age_at_assessment: Optional[int] = None
    total_score: int
    risk_level: str
    recommendations: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class FallRiskList(BaseModel):
    total: int
    items: list[FallRiskAssessmentOut]


class InactivityCheckRequest(BaseModel):
    threshold_hours: float = Field(4.0, ge=1.0, le=24.0,
        description="不活动判定阈值（小时），默认 4h")
    alert_contact: Optional[str] = Field(None, max_length=200,
        description="紧急联系人（姓名+电话），设置后自动生成告警消息")


class InactivityLogOut(BaseModel):
    id: UUID
    member_id: UUID
    period_start: datetime
    period_end: datetime
    duration_hours: float
    status: str
    alert_sent: bool
    alert_contact: Optional[str] = None
    alert_message: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class InactivityLogList(BaseModel):
    total: int
    items: list[InactivityLogOut]


class FallRiskSummary(BaseModel):
    """最新评估 + 风险趋势"""
    assessment_count: int
    latest_assessment: Optional[FallRiskAssessmentOut] = None
    inactivity_log_count: int
    recent_inactivity_hours: Optional[float] = None
