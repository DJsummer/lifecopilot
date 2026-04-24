from __future__ import annotations
"""Pydantic Schema：健康数据录入 / 查询"""
from typing import Optional, List
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.models.health import MetricType, VisitAdviceLevel

# ── 阈值常量（用于异常值过滤） ────────────────────────────────────────
_METRIC_RANGES: dict[MetricType, tuple[float, float]] = {
    MetricType.BLOOD_PRESSURE_SYS: (50, 300),    # mmHg
    MetricType.BLOOD_PRESSURE_DIA: (30, 200),    # mmHg
    MetricType.HEART_RATE:         (20, 300),    # bpm
    MetricType.BLOOD_GLUCOSE:      (1.0, 50.0),  # mmol/L
    MetricType.WEIGHT:             (1.0, 500.0), # kg
    MetricType.HEIGHT:             (20.0, 300.0),# cm
    MetricType.BODY_TEMPERATURE:   (30.0, 45.0), # °C
    MetricType.SPO2:               (50.0, 100.0),# %
    MetricType.STEPS:              (0, 200000),  # 步
    MetricType.SLEEP_HOURS:        (0, 24),      # 小时
}

_METRIC_UNITS: dict[MetricType, str] = {
    MetricType.BLOOD_PRESSURE_SYS: "mmHg",
    MetricType.BLOOD_PRESSURE_DIA: "mmHg",
    MetricType.HEART_RATE:         "bpm",
    MetricType.BLOOD_GLUCOSE:      "mmol/L",
    MetricType.WEIGHT:             "kg",
    MetricType.HEIGHT:             "cm",
    MetricType.BODY_TEMPERATURE:   "°C",
    MetricType.SPO2:               "%",
    MetricType.STEPS:              "步",
    MetricType.SLEEP_HOURS:        "h",
}


# ── 单条录入 ─────────────────────────────────────────────────────────
class HealthRecordCreate(BaseModel):
    metric_type: MetricType
    value: float = Field(..., description="指标数值")
    measured_at: datetime = Field(..., description="测量时间（ISO 8601，含时区）")
    source: str = Field(default="manual", pattern=r"^(manual|wearable|import)$")
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("value")
    @classmethod
    def validate_value_range(cls, v: float, info) -> float:
        metric_type = info.data.get("metric_type")
        if metric_type and metric_type in _METRIC_RANGES:
            lo, hi = _METRIC_RANGES[metric_type]
            if not (lo <= v <= hi):
                raise ValueError(
                    f"{metric_type} 数值 {v} 超出合理范围 [{lo}, {hi}]"
                )
        return v


class HealthRecordResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    metric_type: MetricType
    value: float
    unit: str
    measured_at: datetime
    source: str
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 批量录入（CSV / 列表） ────────────────────────────────────────────
class HealthRecordBatchCreate(BaseModel):
    records: List[HealthRecordCreate] = Field(..., min_length=1, max_length=500)


class HealthRecordBatchResponse(BaseModel):
    created: int
    failed: int
    errors: List[str] = []


# ── 查询参数（用于列表接口） ─────────────────────────────────────────
class HealthRecordListResponse(BaseModel):
    total: int
    items: List[HealthRecordResponse]


# ── 统计摘要（趋势用） ────────────────────────────────────────────────
class MetricStats(BaseModel):
    metric_type: MetricType
    unit: str
    count: int
    latest_value: Optional[float]
    latest_at: Optional[datetime]
    min_value: Optional[float]
    max_value: Optional[float]
    avg_value: Optional[float]


class HealthSummaryResponse(BaseModel):
    member_id: uuid.UUID
    stats: List[MetricStats]
