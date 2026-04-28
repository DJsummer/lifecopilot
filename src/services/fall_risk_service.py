"""
FallRiskService — 老人跌倒风险评估服务（T008）
===============================================
功能：
  1. 规则评分模型（改进版 Morse Fall Scale + Hendrich II 合并）
       - 13 个评分维度，总分 0-26
       - LOW(0-3) / MODERATE(4-7) / HIGH(8-11) / VERY_HIGH(≥12)
  2. 长时间不活动检测
       - 检查成员最后一次 HealthRecord(steps/heart_rate) 时间
       - 超过阈值（默认 4h）则创建 InactivityLog 并生成告警
  3. 紧急联系人告警消息生成（模拟推送，真实推送留接口可扩展）
  4. LLM 生成个性化干预建议（失败时静默降级为规则建议）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.config import settings
from src.models.fall_risk import (
    ActivityStatus, FallRiskAssessment, FallRiskLevel, InactivityLog,
)
from src.models.health import HealthRecord, MetricType
from src.models.member import Member

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上评估由 AI 辅助生成，仅供家庭照护参考，"
    "不构成医学诊断。请结合专业医生意见制定干预方案。"
)

# ── 评分权重表 ────────────────────────────────────────────────────────

_SCORE_WEIGHTS = {
    "has_fall_history": 3,
    "has_osteoporosis": 2,
    "has_neurological_disease": 3,
    "uses_sedatives": 2,
    "has_gait_disorder": 3,
    "uses_walking_aid": 2,
    "has_vision_impairment": 2,
    "has_weakness_or_balance_issue": 3,
    "lives_alone": 2,
    "frequent_nocturia": 2,
    "has_urge_incontinence": 2,
}


def compute_fall_risk_score(assessment: FallRiskAssessment, age: Optional[int]) -> tuple[int, str]:
    """
    根据评估字段计算总分和风险等级。
    返回 (total_score, risk_level)
    """
    score = 0
    for field, weight in _SCORE_WEIGHTS.items():
        if getattr(assessment, field, False):
            score += weight

    # 年龄调整
    if age is not None:
        if age >= 85:
            score += 2
        elif age >= 75:
            score += 1

    if score <= 3:
        level = FallRiskLevel.LOW
    elif score <= 7:
        level = FallRiskLevel.MODERATE
    elif score <= 11:
        level = FallRiskLevel.HIGH
    else:
        level = FallRiskLevel.VERY_HIGH

    return score, level.value


# ── 规则建议（LLM 降级用） ────────────────────────────────────────────

def _rule_recommendations(assessment: FallRiskAssessment) -> str:
    tips = []
    level = assessment.risk_level

    if level == FallRiskLevel.VERY_HIGH.value:
        tips.append("⚠️ 极高风险：建议立即联系家庭医生进行全面跌倒风险评估，考虑住院评估。")
    elif level == FallRiskLevel.HIGH.value:
        tips.append("⚠️ 高风险：建议本周内就诊，由医生评估用药调整和康复训练计划。")

    if assessment.has_fall_history:
        tips.append("• 有跌倒史：检查家中地面隐患（地毯/浴室），安装扶手和防滑垫。")
    if assessment.has_gait_disorder or assessment.uses_walking_aid:
        tips.append("• 步态/平衡问题：建议参加平衡训练（太极拳/物理治疗），规范使用助行器。")
    if assessment.has_vision_impairment:
        tips.append("• 视力下降：优先就眼科配戴合适眼镜，保持室内充足照明。")
    if assessment.uses_sedatives:
        tips.append("• 镇静类药物：勿夜间单独起床，咨询医生评估减量可能性。")
    if assessment.frequent_nocturia or assessment.has_urge_incontinence:
        tips.append("• 夜间如厕风险：床边放置夜灯，考虑睡前减少液体摄入。")
    if assessment.has_weakness_or_balance_issue:
        tips.append("• 肌力下降：每日适量抗阻训练（坐站练习/哑铃），补充钙+维生素D。")
    if assessment.lives_alone:
        tips.append("• 独居风险：设置每日定时报平安机制，考虑佩戴紧急呼叫设备。")
    if assessment.has_osteoporosis:
        tips.append("• 骨质疏松：及时就医评估抗骨质疏松药物治疗，减少骨折风险。")

    if not tips:
        tips.append("• 目前跌倒风险较低，建议保持规律运动和均衡饮食，每年定期复评。")

    return "\n".join(tips) + DISCLAIMER


# ── LLM 干预建议 ──────────────────────────────────────────────────────

async def generate_fall_risk_recommendations(
    member: Member,
    assessment: FallRiskAssessment,
    db: AsyncSession,
) -> str:
    """调用 LLM 生成个性化干预建议；失败时静默降级为规则建议。"""
    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,
        )

        risk_factors = []
        factor_map = {
            "has_fall_history": "近3个月有跌倒史",
            "has_osteoporosis": "骨质疏松",
            "has_neurological_disease": "帕金森/神经系统疾病",
            "uses_sedatives": "使用镇静或催眠药物",
            "has_gait_disorder": "步态异常",
            "uses_walking_aid": "使用助行器",
            "has_vision_impairment": "视力下降",
            "has_weakness_or_balance_issue": "肌力下降/平衡感差",
            "lives_alone": "独居",
            "frequent_nocturia": "夜间如厕频繁",
            "has_urge_incontinence": "急迫性尿失禁",
        }
        for field, label in factor_map.items():
            if getattr(assessment, field, False):
                risk_factors.append(label)

        level_cn = {
            "low": "低风险", "moderate": "中等风险",
            "high": "高风险", "very_high": "极高风险",
        }.get(assessment.risk_level, assessment.risk_level)

        age_str = f"{assessment.age_at_assessment}岁" if assessment.age_at_assessment else "年龄未知"
        prompt = f"""你是老年健康管理顾问，请根据以下跌倒风险评估结果，为{member.nickname}（{age_str}）提供简洁实用的个性化干预建议，中文，不超过200字。

跌倒风险评估结果：
- 总分：{assessment.total_score}/26
- 风险等级：{level_cn}
- 存在的风险因素：{('、'.join(risk_factors)) if risk_factors else '无明显危险因素'}

请给出4-5条针对性干预建议，按优先级排列，包括：
1. 最紧迫的安全措施
2. 医疗建议（如需就诊）
3. 居家环境改善
4. 运动/康复建议"""

        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.5,
        )
        text = resp.choices[0].message.content.strip()
        return text + DISCLAIMER
    except Exception as exc:
        log.warning("LLM fall risk recommendations failed, fallback: %s", exc)
        return _rule_recommendations(assessment)


# ── 长时间不活动检测 ──────────────────────────────────────────────────

async def detect_inactivity(
    member_id,
    db: AsyncSession,
    threshold_hours: float = 4.0,
    alert_contact: Optional[str] = None,
) -> Optional[InactivityLog]:
    """
    检查成员最后一次健康记录（步数/心率）的时间。
    若超过 threshold_hours，则创建一条 InactivityLog。
    返回创建的 InactivityLog，若未达阈值则返回 None。
    """
    now = datetime.now(timezone.utc)

    # 查询最近一条步数或心率记录（活动类指标）
    stmt = (
        select(HealthRecord)
        .where(
            HealthRecord.member_id == member_id,
            HealthRecord.metric_type.in_([
                MetricType.STEPS.value,
                MetricType.HEART_RATE.value,
            ]),
        )
        .order_by(HealthRecord.measured_at.desc())
        .limit(1)
    )
    last_record = (await db.execute(stmt)).scalar_one_or_none()

    if last_record is None:
        # 无记录，无法判断
        return None

    last_time = last_record.measured_at
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)

    gap_hours = (now - last_time).total_seconds() / 3600.0
    if gap_hours < threshold_hours:
        return None

    # 已有未解决的同时段 log 则跳过（30分钟内不重复创建）
    recent_log = (await db.execute(
        select(InactivityLog)
        .where(
            InactivityLog.member_id == member_id,
            InactivityLog.period_start >= now - timedelta(hours=0.5),
        )
    )).scalar_one_or_none()
    if recent_log:
        return None

    alert_msg = (
        f"【LifePilot 健康提醒】您的家人 {member_id} "
        f"已超过 {gap_hours:.1f} 小时没有活动记录，请及时确认其状态。"
    )

    log_entry = InactivityLog(
        member_id=member_id,
        period_start=last_time,
        period_end=now,
        duration_hours=round(gap_hours, 2),
        status=ActivityStatus.INACTIVE.value,
        alert_sent=bool(alert_contact),
        alert_contact=alert_contact,
        alert_message=alert_msg if alert_contact else None,
    )
    db.add(log_entry)
    await db.flush()
    return log_entry
