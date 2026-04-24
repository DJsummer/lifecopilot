"""就医准备助手 ORM 模型（T019）"""
import uuid
from typing import Optional
from enum import Enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class VisitLanguage(str, Enum):
    ZH = "zh"   # 中文
    EN = "en"   # 英文
    BOTH = "both"  # 双语


class VisitSummary(BaseModel):
    """就医前准备摘要"""
    __tablename__ = "visit_summaries"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    # ── 用户填写的就医前问卷 ─────────────────────────────────────────
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)        # 主诉（必填）
    symptom_duration: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)   # 持续时间
    aggravating_factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # 加重因素
    relieving_factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # 缓解因素
    past_medical_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # 既往史（自填）
    visit_language: Mapped[VisitLanguage] = mapped_column(
        String(10), nullable=False, default=VisitLanguage.ZH
    )
    # ── LLM / 系统自动聚合内容 ──────────────────────────────────────
    # 当前活跃用药列表快照 JSON（list of {name, dosage, frequency}）
    medications_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 近期健康指标摘要 JSON（list of {metric_type, latest, avg_7d, unit}）
    health_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 最近检验单异常项 JSON（list of {report_date, report_type, abnormal_items}）
    lab_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM 生成的结构化就诊摘要（中文）
    summary_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM 生成的结构化就诊摘要（英文）
    summary_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="visit_summaries")


from src.models.member import Member  # noqa: E402
