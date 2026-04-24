"""健康周报/月报 Pydantic schemas (T018)"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from src.models.report import ReportPeriod, ReportStatus


class ReportGenerateRequest(BaseModel):
    """生成报告请求"""
    period_type: ReportPeriod
    period_start: date
    period_end: date

    @field_validator("period_end")
    @classmethod
    def end_after_start(cls, v: date, info: Any) -> date:
        start = info.data.get("period_start")
        if start and v < start:
            raise ValueError("period_end 必须不早于 period_start")
        return v


class MetricStatItem(BaseModel):
    """单个指标的统计摘要"""
    metric_type: str
    unit: str
    count: int
    avg: float
    min: float
    max: float
    trend: str          # "上升" / "下降" / "平稳" / "数据不足"
    latest: float


class MedicationStatItem(BaseModel):
    """单种药物依从性统计"""
    name: str
    total_logs: int
    taken: int
    adherence_rate: float   # 0.0 – 1.0


class NotableEvent(BaseModel):
    """异常健康事件"""
    metric_type: str
    value: float
    unit: str
    measured_at: str        # ISO 字符串
    direction: str          # "偏高" / "偏低"


class HealthReportResponse(BaseModel):
    """健康报告详情响应"""
    id: uuid.UUID
    member_id: uuid.UUID
    period_type: ReportPeriod
    period_start: date
    period_end: date
    status: ReportStatus
    metric_stats: Optional[List[MetricStatItem]] = None
    medication_stats: Optional[List[MedicationStatItem]] = None
    notable_events: Optional[List[NotableEvent]] = None
    llm_summary: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class HealthReportListItem(BaseModel):
    """健康报告列表项（不含详细 stats）"""
    id: uuid.UUID
    member_id: uuid.UUID
    period_type: ReportPeriod
    period_start: date
    period_end: date
    status: ReportStatus
    has_llm_summary: bool
    created_at: str

    model_config = {"from_attributes": True}
