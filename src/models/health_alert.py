"""慢病趋势预测 — 告警阈值 & 健康告警模型（T005）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


# ── 枚举 ────────────────────────────────────────────────────────────

class AlertSeverity(str, Enum):
    INFO = "info"          # 轻微偏离
    WARNING = "warning"    # 需要关注
    DANGER = "danger"      # 危险，建议立即就医


class AlertStatus(str, Enum):
    ACTIVE = "active"          # 待处理
    ACKNOWLEDGED = "acknowledged"  # 用户已确认
    RESOLVED = "resolved"      # 已恢复正常


class TrendDirection(str, Enum):
    RISING = "rising"          # 持续升高
    FALLING = "falling"        # 持续下降
    STABLE = "stable"          # 稳定平稳
    FLUCTUATING = "fluctuating"  # 频繁波动


# ── 个性化健康阈值 ────────────────────────────────────────────────────

class HealthThreshold(BaseModel):
    """
    成员某指标的个性化阈值设置。
    每位成员每种指标最多一条记录（unique(member_id, metric_type)）。
    支持上/下限各设置警告线（warning）与危险线（danger）。
    """
    __tablename__ = "health_thresholds"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 上告警限：超过 warning_high → WARNING，超过 danger_high → DANGER
    warning_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    danger_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 下告警限：低于 warning_low → WARNING，低于 danger_low → DANGER
    warning_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    danger_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 是否启用
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 备注（医生建议等）
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="health_thresholds")


# ── 健康告警记录 ─────────────────────────────────────────────────────

class HealthAlert(BaseModel):
    """
    当健康记录触发阈值时自动生成的告警条目。
    一条 HealthRecord 可触发一条 HealthAlert。
    """
    __tablename__ = "health_alerts"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 触发告警的记录值
    triggered_value: Mapped[float] = mapped_column(Float, nullable=False)
    # 触发的阈值（告知用户为何告警）
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    # 超标方向：high / low
    breach_direction: Mapped[str] = mapped_column(String(10), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(String(20), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(
        String(20), nullable=False, default=AlertStatus.ACTIVE
    )
    # 触发时间（来自健康记录的表单时间）
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 用户确认时间
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # AI 解读（可选）
    llm_advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="health_alerts")


# ── 趋势快照 ─────────────────────────────────────────────────────────

class HealthTrendSnapshot(BaseModel):
    """
    定期（或按需）生成的某指标趋势分析快照。
    存放最近 N 条记录的统计量和趋势方向，以及 LLM 生成的解读文本。
    """
    __tablename__ = "health_trend_snapshots"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 分析的数据点数
    data_points: Mapped[int] = mapped_column(Integer, nullable=False)
    # 统计量
    mean_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    std_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 趋势斜率（每天的变化量，正值=升高，负值=下降）
    slope_per_day: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend_direction: Mapped[Optional[TrendDirection]] = mapped_column(String(20), nullable=True)
    # LLM 解读
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="health_trend_snapshots")


from src.models.member import Member  # noqa: E402
