"""健康记录与症状日记模型"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class MetricType(str, Enum):
    BLOOD_PRESSURE_SYS = "blood_pressure_sys"   # 收缩压 mmHg
    BLOOD_PRESSURE_DIA = "blood_pressure_dia"   # 舒张压 mmHg
    HEART_RATE = "heart_rate"                   # 心率 bpm
    BLOOD_GLUCOSE = "blood_glucose"             # 血糖 mmol/L
    WEIGHT = "weight"                           # 体重 kg
    HEIGHT = "height"                           # 身高 cm
    BODY_TEMPERATURE = "body_temperature"       # 体温 °C
    SPO2 = "spo2"                               # 血氧饱和度 %
    STEPS = "steps"                             # 步数
    SLEEP_HOURS = "sleep_hours"                 # 睡眠时长 h


class VisitAdviceLevel(str, Enum):
    SELF_CARE = "self_care"       # 自愈观察
    MONITOR = "monitor"           # 密切观察
    VISIT_SOON = "visit_soon"     # 尽快就医
    EMERGENCY = "emergency"       # 紧急就医


class HealthRecord(BaseModel):
    """单次健康指标记录"""
    __tablename__ = "health_records"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[MetricType] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual / wearable / import
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="health_records")


class SymptomLog(BaseModel):
    """症状日记"""
    __tablename__ = "symptom_logs"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)           # 用户原始描述
    structured_symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # NLP 提取后的 JSON
    severity_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # 1-10
    advice_level: Mapped[Optional[VisitAdviceLevel]] = mapped_column(String(20), nullable=True)
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    member: Mapped["Member"] = relationship(back_populates="symptom_logs")


from src.models.member import Member  # noqa: E402
