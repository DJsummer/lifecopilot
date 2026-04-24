"""症状日记 NLP 分析 Pydantic schemas (T011)"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.models.health import VisitAdviceLevel


class SymptomItem(BaseModel):
    """单个结构化症状条目（LLM 提取）"""
    name: str                       # 症状名称，如 "头痛"
    severity: Optional[str] = None  # 程度描述，如 "剧烈"
    location: Optional[str] = None  # 部位，如 "右侧颞部"
    duration: Optional[str] = None  # 持续时间，如 "3小时"
    character: Optional[str] = None # 性质，如 "搏动性"


class SymptomLogCreate(BaseModel):
    """记录症状日记请求"""
    raw_text: str               # 用户自由描述（必填）
    occurred_at: Optional[datetime] = None  # 发生时间（默认当前时间）

    @field_validator("raw_text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_text 不能为空")
        return v.strip()


class SymptomLogResponse(BaseModel):
    """症状日记详情响应"""
    id: uuid.UUID
    member_id: uuid.UUID
    raw_text: str
    occurred_at: str                  # ISO 时间字符串
    structured_symptoms: Optional[List[SymptomItem]] = None
    severity_score: Optional[int] = None    # 1–10
    advice_level: Optional[VisitAdviceLevel] = None
    llm_summary: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class SymptomLogListItem(BaseModel):
    """症状日记列表项"""
    id: uuid.UUID
    member_id: uuid.UUID
    raw_text: str
    occurred_at: str
    severity_score: Optional[int] = None
    advice_level: Optional[VisitAdviceLevel] = None
    has_analysis: bool              # 是否已完成 LLM 分析
    created_at: str

    model_config = {"from_attributes": True}
