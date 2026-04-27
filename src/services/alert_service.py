"""
AlertService — 慢病趋势预测与告警服务（T005）
==============================================
功能：
  1. 规则引擎：将新录入的健康值与个性化阈值比较，触发 INFO/WARNING/DANGER 告警
  2. 趋势分析：最小二乘法计算近 N 条记录的线性斜率，判定趋势方向
  3. LLM 解读：对趋势快照生成通俗自然语言建议
  4. 默认阈值：支持内置的通用正常范围（无需用户手动配置即可告警）
  5. 告警去重：1 小时内同一指标同方向的告警不重复触发（冷却期）

内置正常范围（用于系统默认阈值判断）：
  ┌─────────────────────┬────────┬────────┬────────┬────────┐
  │ metric_type         │ w_low  │ d_low  │ w_high │ d_high │
  ├─────────────────────┼────────┼────────┼────────┼────────┤
  │ blood_pressure_sys  │  90    │  80    │  140   │  160   │
  │ blood_pressure_dia  │  60    │  50    │   90   │  100   │
  │ heart_rate          │  50    │  40    │  100   │  120   │
  │ blood_glucose       │  3.9   │  3.0   │   7.0  │   11.1 │
  │ body_temperature    │  36.0  │  35.0  │   37.5 │   38.5 │
  │ spo2                │  95    │  90    │  100   │  100   │
  │ weight              │   -    │   -    │   -    │   -    │ (无默认)
  └─────────────────────┴────────┴────────┴────────┴────────┘

趋势判定规则：
  - |slope_per_day| < 阈值_5%/day → STABLE
  - slope > 0 → RISING；slope < 0 → FALLING
  - 波动（std > mean×20%）→ FLUCTUATING
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.config import settings
from src.models.health import HealthRecord, MetricType
from src.models.health_alert import (
    AlertSeverity, AlertStatus, HealthAlert, HealthThreshold, HealthTrendSnapshot,
    TrendDirection,
)
from src.models.member import Member

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上趋势分析由 AI 生成，仅供健康参考，不构成医学诊断。"
    "如需进一步了解，请咨询专业医生。"
)

# ── 内置默认阈值 ─────────────────────────────────────────────────────

_DEFAULT_THRESHOLDS: dict[str, dict] = {
    MetricType.BLOOD_PRESSURE_SYS: {
        "warning_low": 90.0, "danger_low": 80.0,
        "warning_high": 140.0, "danger_high": 160.0,
    },
    MetricType.BLOOD_PRESSURE_DIA: {
        "warning_low": 60.0, "danger_low": 50.0,
        "warning_high": 90.0, "danger_high": 100.0,
    },
    MetricType.HEART_RATE: {
        "warning_low": 50.0, "danger_low": 40.0,
        "warning_high": 100.0, "danger_high": 120.0,
    },
    MetricType.BLOOD_GLUCOSE: {
        "warning_low": 3.9, "danger_low": 3.0,
        "warning_high": 7.0, "danger_high": 11.1,
    },
    MetricType.BODY_TEMPERATURE: {
        "warning_low": 36.0, "danger_low": 35.0,
        "warning_high": 37.5, "danger_high": 38.5,
    },
    MetricType.SPO2: {
        "warning_low": 95.0, "danger_low": 90.0,
        "warning_high": None, "danger_high": None,
    },
}

# 告警冷却期（同一指标同方向，1小时内不重复触发）
_ALERT_COOLDOWN_HOURS = 1


# ── 阈值工具 ─────────────────────────────────────────────────────────

def _get_effective_thresholds(user_threshold: Optional[HealthThreshold], metric_type: str) -> dict:
    """
    合并：用户自定义阈值 > 系统默认阈值。
    返回 {warning_low, danger_low, warning_high, danger_high}，值可为 None。
    """
    defaults = _DEFAULT_THRESHOLDS.get(metric_type, {})
    if user_threshold and user_threshold.enabled:
        return {
            "warning_low": user_threshold.warning_low if user_threshold.warning_low is not None else defaults.get("warning_low"),
            "danger_low": user_threshold.danger_low if user_threshold.danger_low is not None else defaults.get("danger_low"),
            "warning_high": user_threshold.warning_high if user_threshold.warning_high is not None else defaults.get("warning_high"),
            "danger_high": user_threshold.danger_high if user_threshold.danger_high is not None else defaults.get("danger_high"),
        }
    return {k: defaults.get(k) for k in ("warning_low", "danger_low", "warning_high", "danger_high")}


def _classify_breach(value: float, thresholds: dict) -> Optional[tuple[AlertSeverity, float, str]]:
    """
    判断 value 是否超阈值。
    返回 (severity, threshold_value, direction) 或 None。
    优先返回更严重的等级。
    """
    # 高危 > 警告，优先检查 danger
    if thresholds.get("danger_high") is not None and value >= thresholds["danger_high"]:
        return AlertSeverity.DANGER, thresholds["danger_high"], "high"
    if thresholds.get("danger_low") is not None and value <= thresholds["danger_low"]:
        return AlertSeverity.DANGER, thresholds["danger_low"], "low"
    if thresholds.get("warning_high") is not None and value >= thresholds["warning_high"]:
        return AlertSeverity.WARNING, thresholds["warning_high"], "high"
    if thresholds.get("warning_low") is not None and value <= thresholds["warning_low"]:
        return AlertSeverity.WARNING, thresholds["warning_low"], "low"
    return None


# ── 核心告警检测 ──────────────────────────────────────────────────────

async def check_and_create_alert(
    member_id,
    metric_type: str,
    value: float,
    triggered_at: datetime,
    db: AsyncSession,
) -> Optional[HealthAlert]:
    """
    将新录入值与阈值对比，满足条件则创建 HealthAlert。
    同一指标在冷却期内不重复。
    """
    # 获取用户自定义阈值
    stmt = select(HealthThreshold).where(
        HealthThreshold.member_id == member_id,
        HealthThreshold.metric_type == metric_type,
    )
    user_threshold = (await db.execute(stmt)).scalar_one_or_none()
    thresholds = _get_effective_thresholds(user_threshold, metric_type)

    result = _classify_breach(value, thresholds)
    if result is None:
        return None

    severity, threshold_value, direction = result

    # 冷却期检查
    cooldown_start = triggered_at - timedelta(hours=_ALERT_COOLDOWN_HOURS)
    recent_stmt = select(HealthAlert).where(
        HealthAlert.member_id == member_id,
        HealthAlert.metric_type == metric_type,
        HealthAlert.breach_direction == direction,
        HealthAlert.triggered_at >= cooldown_start,
    )
    recent = (await db.execute(recent_stmt)).scalar_one_or_none()
    if recent:
        return None  # 冷却期内，不重复

    alert = HealthAlert(
        member_id=member_id,
        metric_type=metric_type,
        triggered_value=value,
        threshold_value=threshold_value,
        breach_direction=direction,
        severity=severity,
        status=AlertStatus.ACTIVE,
        triggered_at=triggered_at,
    )
    db.add(alert)
    # 注意：不在此 commit，调用方负责 commit
    return alert


# ── 趋势分析（最小二乘线性回归）────────────────────────────────────

def _linear_slope(x: list[float], y: list[float]) -> float:
    """最小二乘法计算斜率（dy/dx）"""
    n = len(x)
    if n < 2:
        return 0.0
    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sxx = sum(xi * xi for xi in x)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-10:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _determine_direction(slope: float, mean: float, std: float) -> TrendDirection:
    """根据斜率和离散程度判断趋势方向"""
    if mean > 0 and std / mean > 0.20:
        return TrendDirection.FLUCTUATING
    if abs(slope) < (mean * 0.005 if mean > 0 else 0.01):
        return TrendDirection.STABLE
    return TrendDirection.RISING if slope > 0 else TrendDirection.FALLING


async def analyze_trend(
    member_id,
    metric_type: str,
    db: AsyncSession,
    n_records: int = 30,
) -> dict:
    """
    从最近 n_records 条健康记录计算趋势统计量。
    返回可直接存入 HealthTrendSnapshot 的 dict。
    """
    stmt = (
        select(HealthRecord)
        .where(HealthRecord.member_id == member_id, HealthRecord.metric_type == metric_type)
        .order_by(HealthRecord.measured_at.desc())
        .limit(n_records)
    )
    records = (await db.execute(stmt)).scalars().all()

    if not records:
        return {"data_points": 0}

    records = list(reversed(records))  # 时间正序
    values = [r.value for r in records]
    base_ts = records[0].measured_at.timestamp()
    days = [(r.measured_at.timestamp() - base_ts) / 86400 for r in records]

    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    std_val = math.sqrt(variance)
    slope = _linear_slope(days, values)
    direction = _determine_direction(slope, mean_val, std_val)

    return {
        "data_points": len(records),
        "mean_value": round(mean_val, 3),
        "min_value": round(min(values), 3),
        "max_value": round(max(values), 3),
        "std_value": round(std_val, 3),
        "slope_per_day": round(slope, 5),
        "trend_direction": direction,
    }


# ── LLM：生成趋势解读 ────────────────────────────────────────────────

async def generate_trend_summary(
    member: Member,
    metric_type: str,
    trend_data: dict,
    db: AsyncSession,
) -> str:
    """LLM 生成通俗趋势解读（失败时返回规则描述）"""
    from datetime import date as _date
    age = None
    if member.birth_date:
        today = _date.today()
        age = today.year - member.birth_date.year - (
            (today.month, today.day) < (member.birth_date.month, member.birth_date.day)
        )

    metric_labels = {
        "blood_pressure_sys": "收缩压（高压）",
        "blood_pressure_dia": "舒张压（低压）",
        "heart_rate": "心率",
        "blood_glucose": "血糖",
        "weight": "体重",
        "body_temperature": "体温",
        "spo2": "血氧饱和度",
        "steps": "每日步数",
        "sleep_hours": "睡眠时长",
        "height": "身高",
    }
    label = metric_labels.get(metric_type, metric_type)
    direction_cn = {
        "rising": "持续上升", "falling": "持续下降",
        "stable": "平稳", "fluctuating": "频繁波动",
    }.get(trend_data.get("trend_direction", "stable"), "")

    prompt = f"""你是一位家庭健康顾问，请用通俗易懂的语言（2-4句话）解读以下健康趋势，给出风险提示和建议。

用户：{member.nickname}（{age}岁）
指标：{label}
数据点数：{trend_data.get('data_points')} 条
均值：{trend_data.get('mean_value')}
最小值：{trend_data.get('min_value')}  最大值：{trend_data.get('max_value')}
标准差：{trend_data.get('std_value')}
每日变化斜率：{trend_data.get('slope_per_day')}
趋势方向：{direction_cn}

请直接给出分析建议，不要重复列出以上数据。"""

    fallback = (
        f"{label}近 {trend_data.get('data_points')} 次记录均值为 {trend_data.get('mean_value')}，"
        f"趋势{direction_cn}。" + DISCLAIMER
    )

    try:
        client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=300,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text + DISCLAIMER if text else fallback
    except Exception as e:
        log.warning("LLM 趋势解读失败: %s", e)
        return fallback


# ── 快捷函数：生成并保存趋势快照 ─────────────────────────────────────

async def create_trend_snapshot(
    member: Member,
    metric_type: str,
    db: AsyncSession,
    n_records: int = 30,
    with_llm: bool = True,
) -> HealthTrendSnapshot:
    """分析趋势并保存到 health_trend_snapshots 表"""
    trend_data = await analyze_trend(member.id, metric_type, db, n_records)

    llm_summary = None
    if with_llm and trend_data.get("data_points", 0) >= 3:
        llm_summary = await generate_trend_summary(member, metric_type, trend_data, db)

    snapshot = HealthTrendSnapshot(
        member_id=member.id,
        metric_type=metric_type,
        data_points=trend_data.get("data_points", 0),
        mean_value=trend_data.get("mean_value"),
        min_value=trend_data.get("min_value"),
        max_value=trend_data.get("max_value"),
        std_value=trend_data.get("std_value"),
        slope_per_day=trend_data.get("slope_per_day"),
        trend_direction=trend_data.get("trend_direction"),
        llm_summary=llm_summary,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot
