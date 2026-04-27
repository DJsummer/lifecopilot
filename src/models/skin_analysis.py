"""皮肤/伤口照片辅助分析模型（T013）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class SkinAnalysisResult(str, Enum):
    NORMAL = "normal"          # 正常，无需特殊处理
    ATTENTION = "attention"    # 需要关注，建议观察
    VISIT_SOON = "visit_soon"  # 建议近期就医
    EMERGENCY = "emergency"    # 需要立即就医


class SkinAnalysis(BaseModel):
    """皮肤/伤口照片辅助分析记录"""
    __tablename__ = "skin_analyses"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    # 上传信息
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 存储路径
    body_part: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)   # 身体部位
    user_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # 用户补充描述

    # AI 分析结果
    result: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SkinAnalysisResult.ATTENTION
    )
    # LLM 返回的结构化分析 JSON
    # {"findings": [...], "possible_conditions": [...], "care_advice": [...]}
    structured_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 通俗语言总结（含免责声明）
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 审计日志：请求 token / 使用模型
    audit_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    member: Mapped["Member"] = relationship(back_populates="skin_analyses")


from src.models.member import Member  # noqa: E402
