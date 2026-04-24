"""Pydantic schemas for lab report endpoints (T012)"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class StructuredItem(BaseModel):
    """单个检验项目结构"""
    name: str
    abbr: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    is_abnormal: bool = False
    direction: Optional[str] = None          # "high" | "low" | None
    clinical_hint: Optional[str] = None


class LabReportUploadResponse(BaseModel):
    """上传检验单后的 AI 解读结果"""
    report_id: uuid.UUID
    member_id: uuid.UUID
    report_type: str
    report_date: date
    hospital: Optional[str] = None
    has_abnormal: bool
    abnormal_summary: Optional[str] = None
    structured_items: List[StructuredItem] = Field(default_factory=list)
    interpretation: str
    advice: Optional[str] = None
    disclaimer: str
    ocr_raw_text: Optional[str] = None      # 可选，返回 OCR 文字供用户核查

    class Config:
        from_attributes = True


class LabReportSummary(BaseModel):
    """列表页简要信息"""
    report_id: uuid.UUID
    member_id: uuid.UUID
    report_type: str
    report_date: date
    hospital: Optional[str] = None
    has_abnormal: bool
    abnormal_summary: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class LabReportDetail(LabReportUploadResponse):
    """单条报告详情（含全量数据）"""
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AbnormalItem(BaseModel):
    """异常项简要（用于趋势比对）"""
    name: str
    value: Optional[str] = None
    unit: Optional[str] = None
    direction: Optional[str] = None


class LabReportCompareItem(BaseModel):
    """趋势对比中的单条记录"""
    report_id: uuid.UUID
    report_date: date
    abnormal_items: List[AbnormalItem] = Field(default_factory=list)

    class Config:
        from_attributes = True
