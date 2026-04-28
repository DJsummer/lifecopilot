"""老人跌倒风险评估模型（T008）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class FallRiskLevel(str, Enum):
    """跌倒风险等级"""
    LOW      = "low"       # 评分 0–3
    MODERATE = "moderate"  # 评分 4–7
    HIGH     = "high"      # 评分 8–11
    VERY_HIGH = "very_high"  # 评分 ≥ 12


class ActivityStatus(str, Enum):
    """活动状态（用于长时间不活动检测）"""
    ACTIVE   = "active"    # 正常活跃
    SEDENTARY = "sedentary"  # 久坐（> 2h 无活动）
    INACTIVE = "inactive"  # 长时间不活动（> 4h，需告警）
    ALERT_SENT = "alert_sent"  # 已发送紧急告警


class FallRiskAssessment(BaseModel):
    """
    跌倒风险问卷评估记录。
    采用改进版 Morse Fall Scale + Hendrich II 合并评分：
    ─────────────────────────────────────────────────
    评分维度（共 13 项，总分 0-26）：
      病史类（0-10）:
        1. 近 3 个月内有跌倒史              → 3
        2. 骨质疏松症诊断                  → 2
        3. 帕金森/神经系统疾病              → 3
        4. 正在使用镇静剂/催眠药/抗抑郁药   → 2

      功能类（0-10）:
        5. 步态异常（拖步/蹒跚/不稳定）     → 3
        6. 需使用助行器/手杖                → 2
        7. 视力下降（未矫正）               → 2
        8. 肌力下降/平衡感差                → 3

      环境/行为类（0-6）:
        9. 独居                            → 2
       10. 夜间如厕频繁（≥2次/夜）          → 2
       11. 急迫性尿失禁                    → 2

      年龄调整（0-2）:
       12. 年龄 ≥ 75 岁                    → 1
       13. 年龄 ≥ 85 岁（额外+1）           → 1

    风险等级：LOW(0-3) / MODERATE(4-7) / HIGH(8-11) / VERY_HIGH(≥12)
    ─────────────────────────────────────────────────
    """
    __tablename__ = "fall_risk_assessments"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="评估时间"
    )

    # ── 病史类评分项 ─────────────────────────────────────────────────
    has_fall_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="近3个月内有跌倒史 → +3")
    has_osteoporosis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="骨质疏松症 → +2")
    has_neurological_disease: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="帕金森/神经系统疾病 → +3")
    uses_sedatives: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="使用镇静剂/催眠药/抗抑郁药 → +2")

    # ── 功能类评分项 ─────────────────────────────────────────────────
    has_gait_disorder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="步态异常 → +3")
    uses_walking_aid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="需助行器/手杖 → +2")
    has_vision_impairment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="视力下降（未矫正） → +2")
    has_weakness_or_balance_issue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="肌力下降/平衡感差 → +3")

    # ── 环境/行为类 ──────────────────────────────────────────────────
    lives_alone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="独居 → +2")
    frequent_nocturia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="夜间如厕频繁（≥2次/夜） → +2")
    has_urge_incontinence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="急迫性尿失禁 → +2")

    # ── 自动计算结果 ─────────────────────────────────────────────────
    age_at_assessment: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="评估时年龄（服务层计算）")
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default=FallRiskLevel.LOW.value)

    # ── LLM 干预建议 ─────────────────────────────────────────────────
    recommendations: Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="LLM 生成的个性化干预建议")

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="fall_risk_assessments")


class InactivityLog(BaseModel):
    """
    不活动记录（基于步数或活动数据检测长时间不活动）。
    当老年成员连续超过 N 小时无活动记录时自动创建，并可触发紧急提醒。
    """
    __tablename__ = "inactivity_logs"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    # 不活动区间
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_hours: Mapped[float] = mapped_column(Float, nullable=False,
        comment="不活动时长（小时）")

    # 状态
    status: Mapped[str] = mapped_column(String(20), nullable=False,
        default=ActivityStatus.INACTIVE.value)
    alert_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 紧急联系人信息（可由成员配置或从 notes 读取）
    alert_contact: Mapped[Optional[str]] = mapped_column(String(200), nullable=True,
        comment="紧急联系人姓名+电话")
    alert_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="告警消息内容")

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="inactivity_logs")


# 延迟导入
from src.models.member import Member  # noqa: E402
