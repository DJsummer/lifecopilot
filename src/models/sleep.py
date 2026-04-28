"""睡眠质量分析模型（T006）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class SleepQuality(str, Enum):
    """主观睡眠质量等级"""
    POOR = "poor"           # 差（score < 40）
    FAIR = "fair"           # 一般（40–59）
    GOOD = "good"           # 良好（60–79）
    EXCELLENT = "excellent" # 优秀（≥ 80）


class ApneaRisk(str, Enum):
    """呼吸暂停风险"""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SleepRecord(BaseModel):
    """
    睡眠记录。
    支持手动录入（用户填写各分期时长）或可穿戴设备导入（自动填充各阶段）。
    sleep_score 由服务层计算写入：
      = 0.35×duration_factor + 0.25×deep_factor + 0.20×rem_factor
        + 0.10×continuity_factor + 0.10×timing_factor (各分项均 0-100)
    """
    __tablename__ = "sleep_records"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    # ── 时间 ─────────────────────────────────────────────────────────
    sleep_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="入睡时间（UTC）",
    )
    sleep_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="起床时间（UTC）",
    )
    # 总时长（分钟），接口层计算后写入
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── 睡眠分期（分钟，均可为 None 表示未知）───────────────────────
    deep_sleep_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="深睡眠时长（分钟）")
    light_sleep_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="浅睡眠时长（分钟）")
    rem_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="REM 快速眼动时长（分钟）")
    awake_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="夜间清醒时长（分钟）")

    # ── 中断次数 ────────────────────────────────────────────────────
    interruptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="夜间觉醒次数")

    # ── SpO2（从当晚 HealthRecord 关联填充，或手动填写）─────────────
    spo2_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
        comment="夜间最低血氧%")
    spo2_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
        comment="夜间平均血氧%")

    # ── 评分 & 等级 ──────────────────────────────────────────────────
    sleep_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="综合睡眠评分 0-100")
    quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True,
        comment="poor / fair / good / excellent")
    apnea_risk: Mapped[Optional[str]] = mapped_column(String(20), nullable=True,
        comment="low / moderate / high")

    # ── 数据来源 ────────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual",
        comment="manual / mi_band / apple_health / fitbit")

    # ── LLM 改善建议 ────────────────────────────────────────────────
    advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── 用户备注 ───────────────────────────────────────────────────
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="sleep_records")


# 延迟导入避免循环
from src.models.member import Member  # noqa: E402
