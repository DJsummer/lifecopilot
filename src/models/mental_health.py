"""心理健康模型（T016）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class RiskLevel(str, Enum):
    LOW = "low"          # 无/轻微（PHQ-9: 0-4 / GAD-7: 0-4）
    MODERATE = "moderate"  # 轻度（PHQ-9: 5-9 / GAD-7: 5-9）
    HIGH = "high"        # 中度（PHQ-9: 10-14 / GAD-7: 10-14）
    CRISIS = "crisis"    # 重度，建议立即寻求专业帮助（PHQ-9: 15+ / GAD-7: 15+）


class EntryType(str, Enum):
    DIARY = "diary"          # 纯情绪日记（LLM 分析）
    PHQ9 = "phq9"            # 仅 PHQ-9 量表
    GAD7 = "gad7"            # 仅 GAD-7 量表
    COMBINED = "combined"    # 情绪日记 + 量表


class MentalHealthLog(BaseModel):
    """心理健康记录（情绪日记 + PHQ-9/GAD-7 量表）"""
    __tablename__ = "mental_health_logs"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[EntryType] = mapped_column(String(20), nullable=False)

    # 情绪日记字段
    emotion_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emotion_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON 数组
    mood_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-10
    nlp_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # LLM 情绪解析

    # PHQ-9 量表字段（9 题，每题 0-3，总分 0-27）
    phq9_answers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON 数组
    phq9_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # GAD-7 量表字段（7 题，每题 0-3，总分 0-21）
    gad7_answers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON 数组
    gad7_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 综合风险
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    resources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # JSON 数组，推荐资源

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    member: Mapped["Member"] = relationship(back_populates="mental_health_logs")


from src.models.member import Member  # noqa: E402
