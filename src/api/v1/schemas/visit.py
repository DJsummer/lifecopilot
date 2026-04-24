"""就医准备助手 Pydantic schemas (T019)"""
from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.models.visit import VisitLanguage


class VisitSummaryCreate(BaseModel):
    """创建就诊摘要请求（用户填写的就医前问卷）"""
    chief_complaint: str               # 主诉（必填）
    symptom_duration: Optional[str] = None          # 持续时间，如 "3天"
    aggravating_factors: Optional[str] = None       # 加重因素
    relieving_factors: Optional[str] = None         # 缓解因素
    past_medical_history: Optional[str] = None      # 既往史（补充，DB 中若有档案可自动注入）
    visit_language: VisitLanguage = VisitLanguage.ZH  # 摘要语言
    # 近期健康数据检索范围（天），默认 30 天
    health_lookback_days: int = 30

    @field_validator("chief_complaint")
    @classmethod
    def complaint_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chief_complaint 不能为空")
        return v.strip()

    @field_validator("health_lookback_days")
    @classmethod
    def check_lookback(cls, v: int) -> int:
        if v < 1 or v > 365:
            raise ValueError("health_lookback_days 需在 1–365 之间")
        return v


# ── 快照子结构 ────────────────────────────────────────────────────────

class MedicationSnapshotItem(BaseModel):
    name: str
    dosage: str
    frequency: str
    instructions: Optional[str] = None


class HealthSnapshotItem(BaseModel):
    metric_type: str
    unit: str
    latest: float
    avg_recent: float   # 近期均值
    count: int


class LabSnapshotItem(BaseModel):
    report_date: str    # ISO date 字符串
    report_type: str
    abnormal_items: Optional[str] = None   # JSON 文本（原样透传）
    has_abnormal: bool


# ── Response ──────────────────────────────────────────────────────────

class VisitSummaryResponse(BaseModel):
    """就诊摘要详情响应"""
    id: uuid.UUID
    member_id: uuid.UUID
    chief_complaint: str
    symptom_duration: Optional[str] = None
    aggravating_factors: Optional[str] = None
    relieving_factors: Optional[str] = None
    past_medical_history: Optional[str] = None
    visit_language: VisitLanguage
    medications_snapshot: Optional[List[MedicationSnapshotItem]] = None
    health_snapshot: Optional[List[HealthSnapshotItem]] = None
    lab_snapshot: Optional[List[LabSnapshotItem]] = None
    summary_zh: Optional[str] = None
    summary_en: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class VisitSummaryListItem(BaseModel):
    """就诊摘要列表项"""
    id: uuid.UUID
    member_id: uuid.UUID
    chief_complaint: str
    visit_language: VisitLanguage
    has_summary_zh: bool
    has_summary_en: bool
    created_at: str

    model_config = {"from_attributes": True}
