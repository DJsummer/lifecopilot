"""
EnvironmentService — 环境健康监控服务（T017）
=============================================
功能：
  1. 环境健康阈值规则引擎（WHO/国标 PM2.5/CO₂/温湿度/VOC/噪音）
  2. 空气质量综合指数（AQI 简化版，取各指标最差等级）
  3. 米家传感器/Home Assistant Webhook 数据接入（适配器模式）
  4. LLM 生成个性化环境改善建议（失败时静默降级）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.environment import (
    AirQualityLevel,
    EnvironmentAdvice,
    EnvironmentRecord,
    EnvMetricType,
)
from src.models.member import Member

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上环境分析由 AI 辅助生成，仅供家庭参考，"
    "如有严重污染请及时通风并就医检查。"
)

# ── 健康阈值（WHO 2021 / 国标 GB/T18883）─────────────────────────────

#  metric_type → {warning: float, danger: float, unit: str, label: str}
_THRESHOLDS: dict[str, dict] = {
    EnvMetricType.PM2_5: {
        "unit": "μg/m³", "label": "PM2.5",
        "warning": 35.0,   # WHO 日均 15, 中国年均 35
        "danger":  75.0,   # 轻度污染上限
    },
    EnvMetricType.PM10: {
        "unit": "μg/m³", "label": "PM10",
        "warning": 70.0,
        "danger":  150.0,
    },
    EnvMetricType.CO2: {
        "unit": "ppm", "label": "CO₂",
        "warning": 1000.0,  # 换气建议阈值
        "danger":  2000.0,  # 明显令人不适
    },
    EnvMetricType.VOC: {
        "unit": "ppb", "label": "VOC",
        "warning": 220.0,   # TVOC 轻度污染
        "danger":  660.0,   # 中度污染
    },
    EnvMetricType.TEMPERATURE: {
        "unit": "°C", "label": "温度",
        "low_warning": 16.0, "low_danger": 10.0,
        "warning": 28.0,    "danger": 35.0,
    },
    EnvMetricType.HUMIDITY: {
        "unit": "%RH", "label": "湿度",
        "low_warning": 30.0, "low_danger": 20.0,
        "warning": 70.0,    "danger": 80.0,
    },
    EnvMetricType.NOISE: {
        "unit": "dB", "label": "噪音",
        "warning": 55.0,   # 睡眠干扰阈值
        "danger":  70.0,   # WHO 听力风险
    },
    EnvMetricType.CO: {
        "unit": "ppm", "label": "CO（一氧化碳）",
        "warning": 9.0,    # WHO 8h 限值
        "danger":  35.0,   # 短期暴露危险
    },
}

# ── 空气质量等级映射（PM2.5 主导）────────────────────────────────────

_PM25_AQI = [
    (0,   AirQualityLevel.EXCELLENT),
    (12,  AirQualityLevel.GOOD),
    (35,  AirQualityLevel.MODERATE),
    (75,  AirQualityLevel.POOR),
    (150, AirQualityLevel.VERY_POOR),
    (250, AirQualityLevel.HAZARDOUS),
]


def _pm25_to_level(pm25: float) -> AirQualityLevel:
    level = AirQualityLevel.HAZARDOUS
    for threshold, lvl in _PM25_AQI:
        if pm25 <= threshold:
            level = lvl
            break
    return level


_LEVEL_RANK = {
    AirQualityLevel.EXCELLENT: 0,
    AirQualityLevel.GOOD: 1,
    AirQualityLevel.MODERATE: 2,
    AirQualityLevel.POOR: 3,
    AirQualityLevel.VERY_POOR: 4,
    AirQualityLevel.HAZARDOUS: 5,
}


def compute_air_quality_level(records: list[EnvironmentRecord]) -> AirQualityLevel:
    """
    根据最近若干条环境记录计算综合空气质量等级。
    取各指标最差等级作为综合结果；无数据时返回 GOOD（假设正常）。
    """
    if not records:
        return AirQualityLevel.GOOD

    worst = AirQualityLevel.EXCELLENT
    for r in records:
        lvl = _single_record_level(r)
        if _LEVEL_RANK[lvl] > _LEVEL_RANK[worst]:
            worst = lvl
    return worst


def _single_record_level(record: EnvironmentRecord) -> AirQualityLevel:
    """将单条记录映射到空气质量等级。"""
    mt = record.metric_type
    v = record.value
    cfg = _THRESHOLDS.get(mt)
    if not cfg:
        return AirQualityLevel.GOOD

    # CO 和 PM 系列直接按 danger/warning 两级
    if "danger" in cfg and v >= cfg["danger"]:
        return AirQualityLevel.VERY_POOR
    if "warning" in cfg and v >= cfg["warning"]:
        return AirQualityLevel.MODERATE

    # 温湿度低值告警
    if "low_danger" in cfg and v <= cfg["low_danger"]:
        return AirQualityLevel.POOR
    if "low_warning" in cfg and v <= cfg["low_warning"]:
        return AirQualityLevel.MODERATE

    return AirQualityLevel.GOOD


def check_threshold(metric_type: str, value: float) -> tuple[bool, Optional[str]]:
    """
    检查单个指标值是否超出阈值。
    返回 (is_alert, alert_level)，alert_level 为 "warning" | "danger" | None。
    """
    cfg = _THRESHOLDS.get(metric_type)
    if not cfg:
        return False, None

    # 高值告警
    if "danger" in cfg and value >= cfg["danger"]:
        return True, "danger"
    if "warning" in cfg and value >= cfg["warning"]:
        return True, "warning"

    # 低值告警（温湿度）
    if "low_danger" in cfg and value <= cfg["low_danger"]:
        return True, "danger"
    if "low_warning" in cfg and value <= cfg["low_warning"]:
        return True, "warning"

    return False, None


def get_default_unit(metric_type: str) -> str:
    cfg = _THRESHOLDS.get(metric_type, {})
    return cfg.get("unit", "")


# ── 规则建议（LLM 降级用）────────────────────────────────────────────

def _rule_advice(records: list[EnvironmentRecord], level: AirQualityLevel) -> str:
    tips = []

    by_type: dict[str, float] = {}
    for r in records:
        by_type.setdefault(r.metric_type, r.value)

    pm25 = by_type.get(EnvMetricType.PM2_5)
    co2  = by_type.get(EnvMetricType.CO2)
    temp = by_type.get(EnvMetricType.TEMPERATURE)
    hum  = by_type.get(EnvMetricType.HUMIDITY)
    voc  = by_type.get(EnvMetricType.VOC)
    co   = by_type.get(EnvMetricType.CO)
    noise = by_type.get(EnvMetricType.NOISE)

    if level in (AirQualityLevel.VERY_POOR, AirQualityLevel.HAZARDOUS):
        tips.append("⚠️ 空气质量极差，建议立即开窗通风或使用空气净化器，减少室内活动。")
    elif level == AirQualityLevel.POOR:
        tips.append("⚠️ 空气质量较差，建议开启净化器并减少激烈运动。")
    elif level == AirQualityLevel.MODERATE:
        tips.append("• 空气质量轻度污染，敏感人群（哮喘/儿童/老人）建议减少户外活动。")

    if pm25 is not None and pm25 > 35:
        tips.append(f"• PM2.5 {pm25:.1f} μg/m³ 偏高：建议关闭窗户，使用 HEPA 净化器，外出佩戴 N95 口罩。")
    if co2 is not None and co2 > 1000:
        tips.append(f"• CO₂ {co2:.0f} ppm 偏高：立即开窗换气 10-15 分钟，保持室内通风。")
    if co is not None and co > 9:
        tips.append(f"• ⚠️ CO 一氧化碳 {co:.1f} ppm，请立即开窗并检查燃气/热水器，必要时拨打 119。")
    if voc is not None and voc > 220:
        tips.append(f"• VOC 挥发性有机物 {voc:.0f} ppb 偏高：检查新装修材料/油漆，保持通风。")
    if temp is not None:
        if temp < 16:
            tips.append(f"• 室温 {temp:.1f}°C 偏低：建议开暖气，老人/儿童注意保暖，防止感冒。")
        elif temp > 28:
            tips.append(f"• 室温 {temp:.1f}°C 偏高：建议开空调（设置 26°C），保持适当通风。")
    if hum is not None:
        if hum < 30:
            tips.append(f"• 湿度 {hum:.0f}% 偏低：建议使用加湿器（目标 40-60%），防止皮肤干燥和呼吸道不适。")
        elif hum > 70:
            tips.append(f"• 湿度 {hum:.0f}% 偏高：开启除湿机或空调除湿，防止霉菌滋生。")
    if noise is not None and noise > 55:
        tips.append(f"• 噪音 {noise:.0f} dB 偏高：睡眠时建议使用耳塞或白噪音机器。")

    if not tips:
        tips.append("• 当前环境各项指标良好，请继续保持良好的通风和清洁习惯。")

    return "\n".join(tips) + DISCLAIMER


# ── LLM 建议────────────────────────────────────────────────────────

async def generate_environment_advice(
    family_id, records: list[EnvironmentRecord], level: AirQualityLevel, db: AsyncSession
) -> str:
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

        summary_lines = []
        for r in records:
            cfg = _THRESHOLDS.get(r.metric_type, {})
            label = cfg.get("label", r.metric_type)
            summary_lines.append(f"  - {label}: {r.value} {r.unit}")

        prompt = (
            f"当前家庭环境监测数据如下（综合空气质量等级：{level.value}）：\n"
            + "\n".join(summary_lines)
            + "\n\n请用简洁中文给出 3-5 条具体可操作的环境改善建议，"
            "涵盖通风、净化、温湿度调节等方面，特别关注儿童和老人的健康影响。"
            "每条建议加 • 前缀。最后附加免责声明。"
        )

        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=500,
        )
        text = resp.choices[0].message.content or ""
        if DISCLAIMER not in text:
            text += DISCLAIMER
        return text
    except Exception as exc:
        log.warning("环境建议 LLM 调用失败，降级为规则建议: %s", exc)
        return _rule_advice(records, level)


# ── 小米/Home Assistant 数据适配器 ────────────────────────────────────

def parse_xiaomi_payload(payload: dict) -> list[dict]:
    """
    解析小米传感器 Webhook 推送格式（米家 IoT 云 → Webhook）。
    返回标准化的 {metric_type, value, unit, device_id, location} 列表。
    期望 payload 格式：
      {
        "did": "lumi.sensor_ht.xxxx",
        "model": "lumi.sensor_ht",
        "attrs": {"temperature": 23.5, "humidity": 55.0}
      }
    """
    did = payload.get("did", "")
    attrs = payload.get("attrs", {})
    results = []

    mi_map = {
        "temperature": (EnvMetricType.TEMPERATURE, "°C"),
        "humidity":    (EnvMetricType.HUMIDITY,    "%RH"),
        "pm2_5_density": (EnvMetricType.PM2_5,    "μg/m³"),
        "co2":         (EnvMetricType.CO2,         "ppm"),
    }
    for key, value in attrs.items():
        if key in mi_map:
            mt, unit = mi_map[key]
            try:
                results.append({
                    "metric_type": mt,
                    "value": float(value),
                    "unit": unit,
                    "device_id": did,
                    "device_type": "xiaomi",
                })
            except (TypeError, ValueError):
                pass
    return results


def parse_home_assistant_payload(payload: dict) -> list[dict]:
    """
    解析 Home Assistant Webhook 推送格式。
    期望 payload 格式（HA → Webhook integration）：
      {
        "entity_id": "sensor.living_room_co2",
        "state": "952",
        "attributes": {"unit_of_measurement": "ppm", "friendly_name": "客厅CO2"}
      }
    """
    entity_id = payload.get("entity_id", "")
    state = payload.get("state")
    attrs = payload.get("attributes", {})
    unit = attrs.get("unit_of_measurement", "")

    # 根据 entity_id 推断指标类型
    ha_map = {
        "pm2_5": (EnvMetricType.PM2_5, "μg/m³"),
        "pm10":  (EnvMetricType.PM10,  "μg/m³"),
        "co2":   (EnvMetricType.CO2,   "ppm"),
        "voc":   (EnvMetricType.VOC,   "ppb"),
        "temperature": (EnvMetricType.TEMPERATURE, "°C"),
        "humidity":    (EnvMetricType.HUMIDITY,    "%RH"),
        "noise":  (EnvMetricType.NOISE, "dB"),
        "carbon_monoxide": (EnvMetricType.CO,      "ppm"),
    }

    metric_type = None
    mapped_unit = unit
    for key, (mt, default_unit) in ha_map.items():
        if key in entity_id:
            metric_type = mt
            mapped_unit = unit or default_unit
            break

    if metric_type is None or state is None:
        return []

    try:
        return [{
            "metric_type": metric_type,
            "value": float(state),
            "unit": mapped_unit,
            "device_id": entity_id,
            "device_type": "home_assistant",
        }]
    except (TypeError, ValueError):
        return []
