"""慢病趋势预测 Schemas（T005）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.health_alert import AlertSeverity, AlertStatus, TrendDirection
from src.models.health import MetricType


# ══════════════════════════════════════════════════════════════════════
# 阈值配置
# ══════════════════════════════════════════════════════════════════════

class ThresholdCreate(BaseModel):
    metric_type: MetricType
    warning_low: Optional[float] = None
    danger_low: Optional[float] = None
    warning_high: Optional[float] = None
    danger_high: Optional[float] = None
    enabled: bool = True
    notes: Optional[str] = None


class ThresholdOut(BaseModel):
    id: UUID
    member_id: UUID
    metric_type: str
    warning_low: Optional[float] = None
    danger_low: Optional[float] = None
    warning_high: Optional[float] = None
    danger_high: Optional[float] = None
    enabled: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ThresholdList(BaseModel):
    total: int
    items: list[ThresholdOut]


# ══════════════════════════════════════════════════════════════════════
# 告警
# ══════════════════════════════════════════════════════════════════════

class AlertOut(BaseModel):
    id: UUID
    member_id: UUID
    metric_type: str
    triggered_value: float
    threshold_value: float
    breach_direction: str
    severity: str
    status: str
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    llm_advice: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AlertList(BaseModel):
    total: int
    items: list[AlertOut]


class AlertAcknowledge(BaseModel):
    llm_advice: Optional[str] = None  # 可传入用户备注


# ══════════════════════════════════════════════════════════════════════
# 趋势快照
# ══════════════════════════════════════════════════════════════════════

class TrendSnapshotOut(BaseModel):
    id: UUID
    member_id: UUID
    metric_type: str
    data_points: int
    mean_value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    std_value: Optional[float] = None
    slope_per_day: Optional[float] = None
    trend_direction: Optional[str] = None
    llm_summary: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class TrendRequest(BaseModel):
    metric_type: MetricType
    n_records: int = Field(30, ge=5, le=365)
    with_llm: bool = True
