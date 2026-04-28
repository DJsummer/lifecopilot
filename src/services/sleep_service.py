"""
SleepService — 睡眠质量分析服务（T006）
=========================================
功能：
  1. 睡眠评分算法（0-100）
       = 0.35×duration_factor    (成人 7-9h 最佳)
       + 0.25×deep_factor        (深睡眠 ≥ 20% 满分)
       + 0.20×rem_factor         (REM ≥ 20% 满分)
       + 0.10×continuity_factor  (觉醒次数 < 2 满分)
       + 0.10×timing_factor      (SpO₂ min ≥ 95% 满分)
  2. 呼吸暂停风险检测（SpO₂ < 90% → high，< 94% → moderate）
  3. 近 N 次记录趋势（得分均值、连续低质量检测）
  4. LLM 生成个性化改善建议（失败时降级为规则建议）
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.core.config import settings
from src.models.sleep import SleepRecord, SleepQuality, ApneaRisk
from src.models.member import Member

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上睡眠分析由 AI 生成，仅供健康参考，不构成医学诊断。"
    "如需进一步了解，请咨询专业医生。"
)

# ── 评分权重 ────────────────────────────────────────────────────────

_W_DURATION     = 0.35
_W_DEEP         = 0.25
_W_REM          = 0.20
_W_CONTINUITY   = 0.10
_W_TIMING       = 0.10  # 用 SpO2 作为呼吸质量代理


# ── 睡眠评分 ────────────────────────────────────────────────────────

def calculate_sleep_score(record: SleepRecord) -> tuple[int, str, str]:
    """
    根据睡眠记录计算综合评分，返回 (score, quality, apnea_risk)。
    缺失字段按保守估算处理（不影响已有字段的得分贡献）。
    """
    # 1. 时长因子：7-9 h 满分，低于 5h 或 > 11h 接近 0
    hours = record.total_minutes / 60.0
    if hours >= 7.0 and hours <= 9.0:
        d_score = 100
    elif hours >= 6.0 and hours < 7.0:
        d_score = int(70 + (hours - 6.0) * 30)
    elif hours > 9.0 and hours <= 10.0:
        d_score = int(100 - (hours - 9.0) * 30)
    elif hours < 6.0 and hours >= 4.0:
        d_score = int(70 * (hours - 4.0) / 2.0)
    elif hours > 10.0:
        d_score = max(0, int(70 - (hours - 10.0) * 40))
    else:
        d_score = 0

    # 2. 深睡眠因子：深睡眠比例 ≥ 20% 满分
    if record.deep_sleep_minutes is not None and record.total_minutes > 0:
        deep_ratio = record.deep_sleep_minutes / record.total_minutes
        dp_score = min(100, int(deep_ratio / 0.20 * 100))
    else:
        dp_score = 60  # 缺失保守估算

    # 3. REM 因子：REM 比例 ≥ 20% 满分
    if record.rem_minutes is not None and record.total_minutes > 0:
        rem_ratio = record.rem_minutes / record.total_minutes
        rem_score = min(100, int(rem_ratio / 0.20 * 100))
    else:
        rem_score = 60

    # 4. 连续性因子：觉醒次数 0-1 满分，≥ 5 接近 0
    if record.interruptions is not None:
        cont_score = max(0, min(100, int((5 - record.interruptions) / 5.0 * 100)))
    else:
        cont_score = 70

    # 5. 血氧因子：SpO2_min ≥ 95 满分，< 85 为 0
    if record.spo2_min is not None:
        if record.spo2_min >= 95:
            timing_score = 100
        elif record.spo2_min >= 90:
            timing_score = int((record.spo2_min - 90) / 5.0 * 100)
        else:
            timing_score = 0
    else:
        timing_score = 75  # 缺失保守估算

    score = int(
        _W_DURATION * d_score
        + _W_DEEP * dp_score
        + _W_REM * rem_score
        + _W_CONTINUITY * cont_score
        + _W_TIMING * timing_score
    )
    score = max(0, min(100, score))

    # 等级
    if score >= 80:
        quality = SleepQuality.EXCELLENT
    elif score >= 60:
        quality = SleepQuality.GOOD
    elif score >= 40:
        quality = SleepQuality.FAIR
    else:
        quality = SleepQuality.POOR

    # 呼吸暂停风险
    if record.spo2_min is not None and record.spo2_min < 90:
        apnea = ApneaRisk.HIGH
    elif record.spo2_min is not None and record.spo2_min < 94:
        apnea = ApneaRisk.MODERATE
    else:
        apnea = ApneaRisk.LOW

    return score, quality.value, apnea.value


# ── 趋势分析 ────────────────────────────────────────────────────────

async def analyze_sleep_trend(
    member_id,
    db: AsyncSession,
    n_days: int = 7,
) -> dict:
    """
    查询近 n_days 天睡眠记录，汇总统计，检测连续低质量。
    返回 dict 供 LLM 和路由层使用。
    """
    stmt = (
        select(SleepRecord)
        .where(SleepRecord.member_id == member_id)
        .order_by(SleepRecord.sleep_start.desc())
        .limit(n_days)
    )
    rows = list((await db.execute(stmt)).scalars())

    if not rows:
        return {"count": 0}

    scores = [r.sleep_score for r in rows if r.sleep_score is not None]
    hours_list = [r.total_minutes / 60.0 for r in rows]
    poor_count = sum(1 for r in rows if r.quality in ("poor", "fair"))
    apnea_high = sum(1 for r in rows if r.apnea_risk == "high")

    avg_score = sum(scores) / len(scores) if scores else None
    avg_hours = sum(hours_list) / len(hours_list)
    min_spo2_vals = [r.spo2_min for r in rows if r.spo2_min is not None]

    return {
        "count": len(rows),
        "avg_score": round(avg_score, 1) if avg_score is not None else None,
        "avg_hours": round(avg_hours, 1),
        "poor_or_fair_count": poor_count,
        "apnea_high_count": apnea_high,
        "min_spo2_overall": min(min_spo2_vals) if min_spo2_vals else None,
        "recent_scores": scores[:7],
    }


# ── 规则建议（LLM 降级用） ────────────────────────────────────────────

def _rule_advice(record: SleepRecord, trend: dict) -> str:
    tips = []
    hours = record.total_minutes / 60.0
    if hours < 6:
        tips.append("睡眠时长不足，建议保证每晚 7-9 小时睡眠。")
    elif hours > 10:
        tips.append("睡眠时间过长，可能影响睡眠质量，建议规律作息。")
    if record.deep_sleep_minutes is not None and record.total_minutes > 0:
        if record.deep_sleep_minutes / record.total_minutes < 0.15:
            tips.append("深睡眠比例偏低，建议睡前避免咖啡因、规律运动。")
    if record.interruptions is not None and record.interruptions >= 3:
        tips.append("夜间觉醒次数较多，建议检查睡眠环境（噪音/光线/温度）。")
    if record.apnea_risk == "high":
        tips.append("⚠️ 夜间血氧过低，有呼吸暂停风险，建议尽快就医检查。")
    elif record.apnea_risk == "moderate":
        tips.append("夜间血氧偏低，建议侧卧入睡并监测变化。")
    if trend.get("poor_or_fair_count", 0) >= 3:
        tips.append("近期多晚睡眠质量不佳，建议保持固定睡眠时间、睡前避免手机屏幕。")
    if not tips:
        tips.append("睡眠质量良好，继续保持规律作息。")
    return "\n".join(f"• {t}" for t in tips) + DISCLAIMER


# ── LLM 建议 ────────────────────────────────────────────────────────

async def generate_sleep_advice(
    member: Member,
    record: SleepRecord,
    trend: dict,
    db: AsyncSession,
) -> str:
    """调用 LLM 生成通俗改善建议；失败时静默降级为规则建议。"""
    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,
        )

        from datetime import date
        age = None
        if member.birth_date:
            today = date.today()
            age = today.year - member.birth_date.year - (
                (today.month, today.day) < (member.birth_date.month, member.birth_date.day)
            )

        hours = record.total_minutes / 60.0
        prompt = f"""你是家庭健康顾问，请根据以下睡眠数据为{member.nickname}（{'%d岁' % age if age else '年龄未知'}）给出简洁实用的改善建议，中文回答，不超过 150 字。

睡眠数据：
- 时长：{hours:.1f} 小时
- 评分：{record.sleep_score}/100（{record.quality}）
- 深睡眠：{record.deep_sleep_minutes or '未知'} 分钟
- REM：{record.rem_minutes or '未知'} 分钟
- 觉醒次数：{record.interruptions if record.interruptions is not None else '未知'}
- 最低血氧：{record.spo2_min or '未知'}%
- 呼吸暂停风险：{record.apnea_risk or '未知'}
- 近{trend.get('count', 0)}天平均评分：{trend.get('avg_score', '未知')}

请给出 3-4 条针对性建议，重点说明最需要改善的点。"""

        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.5,
        )
        text = resp.choices[0].message.content.strip()
        return text + DISCLAIMER
    except Exception as exc:
        log.warning("LLM sleep advice failed, fallback to rule: %s", exc)
        return _rule_advice(record, trend)
