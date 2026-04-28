"""儿童生长发育评估模型（T007）"""
import uuid
from typing import Optional
from datetime import date
from enum import Enum

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class GrowthCategory(str, Enum):
    """百分位等级（基于 WHO 标准）"""
    SEVERE_UNDERWEIGHT = "severe_underweight"   # P< 1
    UNDERWEIGHT        = "underweight"           # P1–P3
    BELOW_AVERAGE      = "below_average"         # P3–P15
    NORMAL             = "normal"                # P15–P85
    ABOVE_AVERAGE      = "above_average"         # P85–P97
    OVERWEIGHT         = "overweight"            # P97–P99
    OBESE              = "obese"                 # P>99


class MilestoneType(str, Enum):
    """发育里程碑类型"""
    MOTOR       = "motor"        # 大运动（翻身/坐/站/走）
    FINE_MOTOR  = "fine_motor"   # 精细动作（抓握/捏）
    LANGUAGE    = "language"     # 语言（发音/词汇/句子）
    COGNITIVE   = "cognitive"    # 认知（认物/问题解决）
    SOCIAL      = "social"       # 社会情感（微笑/依恋/分享）


class MilestoneStatus(str, Enum):
    """里程碑达成状态"""
    ACHIEVED  = "achieved"   # 已达成
    IN_PROGRESS = "in_progress"  # 进行中
    DELAYED   = "delayed"    # 延迟（过了典型年龄窗口仍未达成）


# ── 生长测量记录 ─────────────────────────────────────────────────────

class GrowthRecord(BaseModel):
    """
    儿童生长测量记录（单次）。
    每次测量记录身高/体重，服务层自动计算：
      - BMI = weight / (height_m^2)
      - WHO 百分位（height_for_age / weight_for_age / bmi_for_age）
      - Z-score
      - 等级（GrowthCategory）
    """
    __tablename__ = "growth_records"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    measured_at: Mapped[date] = mapped_column(Date, nullable=False, comment="测量日期")

    # ── 测量值 ────────────────────────────────────────────────────────
    height_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="身高（cm）")
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="体重（kg）")
    head_circumference_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
        comment="头围（cm）—— 婴幼儿重要指标")

    # ── 计算结果（服务层写入）────────────────────────────────────────
    bmi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    age_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="测量时月龄（服务层从 birth_date 计算）")

    # 百分位（0–100）
    height_percentile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_percentile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bmi_percentile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Z-score
    height_zscore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_zscore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 等级评定
    height_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    weight_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    bmi_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── LLM 评估总结 ─────────────────────────────────────────────────
    assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="LLM 生成的综合评估与建议")

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="growth_records")


# ── 发育里程碑 ────────────────────────────────────────────────────────

class DevelopmentMilestone(BaseModel):
    """
    发育里程碑记录。
    记录儿童是否达成某个发育节点（运动/语言/认知/社会情感）。
    多条记录可描述同一类型的多个里程碑节点。
    """
    __tablename__ = "development_milestones"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    # 里程碑基本信息
    milestone_type: Mapped[str] = mapped_column(String(20), nullable=False,
        comment="motor / fine_motor / language / cognitive / social")
    title: Mapped[str] = mapped_column(String(200), nullable=False,
        comment="里程碑名称，如'能独立行走'")

    # 典型达成月龄范围（WHO/AAP 参考）
    typical_age_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="典型达成月龄下限")
    typical_age_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="典型达成月龄上限")

    # 实际达成情况
    status: Mapped[str] = mapped_column(String(20), nullable=False,
        default=MilestoneStatus.IN_PROGRESS.value)
    achieved_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True,
        comment="实际达成日期（已达成时填写）")
    achieved_age_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="达成时月龄")

    # 是否为系统预设里程碑（vs 家长自定义）
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="development_milestones")


# 延迟导入避免循环
from src.models.member import Member  # noqa: E402
