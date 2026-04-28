"""环境健康监控 Schemas（T017）"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EnvironmentRecordCreate(BaseModel):
    metric_type: str = Field(..., description="指标类型: pm2_5/pm10/co2/voc/temperature/humidity/noise/co")
    value: float = Field(..., description="测量值")
    unit: Optional[str] = Field(None, description="单位（不填则自动填充）")
    device_id: Optional[str] = Field(None, max_length=100, description="设备 ID")
    device_type: str = Field("manual", description="数据来源: manual/xiaomi/home_assistant/webhook")
    location: Optional[str] = Field(None, max_length=100, description="房间/位置，如 bedroom")
    measured_at: datetime = Field(..., description="采集时间（ISO 8601，含时区）")
    notes: Optional[str] = None

    @field_validator("metric_type")
    @classmethod
    def validate_metric_type(cls, v: str) -> str:
        allowed = {"pm2_5", "pm10", "co2", "voc", "temperature", "humidity", "noise", "co"}
        if v not in allowed:
            raise ValueError(f"metric_type 必须为 {allowed} 之一")
        return v


class EnvironmentRecordOut(BaseModel):
    id: UUID
    family_id: UUID
    metric_type: str
    value: float
    unit: str
    device_id: Optional[str] = None
    device_type: str
    location: Optional[str] = None
    measured_at: datetime
    is_alert: bool
    alert_level: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class EnvironmentRecordList(BaseModel):
    total: int
    items: list[EnvironmentRecordOut]


class EnvironmentSummary(BaseModel):
    """当前室内环境综合摘要（各指标最新一条 + 综合空气质量等级）"""
    family_id: UUID
    air_quality_level: str
    record_count: int
    latest_records: list[EnvironmentRecordOut]
    alert_count: int


class AdviceRequest(BaseModel):
    """请求生成 LLM 环境建议（可指定近 N 小时窗口）"""
    hours: int = Field(2, ge=1, le=48, description="使用最近 N 小时的数据生成建议，默认 2h")
    location: Optional[str] = Field(None, description="仅分析指定位置，为空则全屋综合")


class EnvironmentAdviceOut(BaseModel):
    id: UUID
    family_id: UUID
    air_quality_level: str
    pm2_5_value: Optional[float] = None
    co2_value: Optional[float] = None
    temperature_value: Optional[float] = None
    humidity_value: Optional[float] = None
    advice_text: str
    generated_at: datetime
    created_at: datetime
    model_config = {"from_attributes": True}


class XiaomiWebhookPayload(BaseModel):
    """小米传感器 Webhook 推送格式"""
    did: str = Field(..., description="设备 DID")
    model: Optional[str] = None
    attrs: dict = Field(..., description="属性键值对，如 {'temperature': 23.5}")


class HomeAssistantWebhookPayload(BaseModel):
    """Home Assistant Webhook 推送格式"""
    entity_id: str
    state: str
    attributes: dict = Field(default_factory=dict)
