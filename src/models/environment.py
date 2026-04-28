"""环境健康监控模型（T017）"""
import uuid
from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class EnvMetricType(str, Enum):
    """环境指标类型"""
    PM2_5       = "pm2_5"       # 细颗粒物，μg/m³
    PM10        = "pm10"        # 可吸入颗粒物，μg/m³
    CO2         = "co2"         # 二氧化碳，ppm
    VOC         = "voc"         # 挥发性有机物，ppb
    TEMPERATURE = "temperature" # 温度，°C
    HUMIDITY    = "humidity"    # 湿度，%RH
    NOISE       = "noise"       # 噪音，dB
    CO          = "co"          # 一氧化碳，ppm


class AirQualityLevel(str, Enum):
    """空气质量等级（AQI 简化版）"""
    EXCELLENT = "excellent"  # 优
    GOOD      = "good"       # 良
    MODERATE  = "moderate"   # 轻度污染
    POOR      = "poor"       # 中度污染
    VERY_POOR = "very_poor"  # 重度污染
    HAZARDOUS = "hazardous"  # 危险


class DeviceType(str, Enum):
    """数据来源设备类型"""
    MANUAL        = "manual"         # 手动录入
    XIAOMI        = "xiaomi"         # 小米传感器
    HOME_ASSISTANT = "home_assistant" # Home Assistant
    WEBHOOK       = "webhook"         # 第三方 Webhook 推送


class EnvironmentRecord(BaseModel):
    """
    单次环境指标采集记录。

    支持多类型传感器：PM2.5/CO₂/温湿度/VOC/噪音/CO
    兼容手动录入、小米传感器、Home Assistant 三类来源。
    """
    __tablename__ = "environment_records"

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="设备唯一标识")
    device_type: Mapped[str] = mapped_column(String(30), nullable=False, default=DeviceType.MANUAL)
    location: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="房间/位置，如 bedroom/living_room")
    metric_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否超过健康阈值")
    alert_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="告警等级 warning/danger")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    family: Mapped["Family"] = relationship(  # type: ignore[name-defined]
        "Family",
        primaryjoin="EnvironmentRecord.family_id == Family.id",
        foreign_keys=[family_id],
        lazy="noload",
    )


class EnvironmentAdvice(BaseModel):
    """
    环境健康 LLM 建议记录。

    存储最近一次 LLM 根据当前环境数据生成的综合改善建议。
    """
    __tablename__ = "environment_advice"

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    air_quality_level: Mapped[str] = mapped_column(String(20), nullable=False)
    pm2_5_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    co2_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temperature_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    humidity_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    advice_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    family: Mapped["Family"] = relationship(  # type: ignore[name-defined]
        "Family",
        primaryjoin="EnvironmentAdvice.family_id == Family.id",
        foreign_keys=[family_id],
        lazy="noload",
    )
