"""皮肤/伤口照片辅助分析 Schemas（T013）"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class SkinAnalysisOut(BaseModel):
    id: UUID
    member_id: UUID
    body_part: Optional[str]
    user_description: Optional[str]
    result: str
    structured_analysis: Optional[Dict[str, Any]] = None
    llm_summary: Optional[str]
    audit_model: Optional[str]
    occurred_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("structured_analysis", mode="before")
    @classmethod
    def parse_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v


class SkinAnalysisList(BaseModel):
    total: int
    items: List[SkinAnalysisOut]
