"""
FitnessService — 运动方案生成与追踪服务（T015）
================================================
功能：
  1. 体能评估问卷 → LLM 生成个性化 4 周运动计划（类型/强度/时长/频率）
  2. 运动日志记录 → LLM 估算热量消耗并给出恢复建议
  3. 每周运动汇总（完成次数/总时长/热量/心率均值）
  4. 动态调整：根据连续日志表现重新生成计划
  5. LLM 调用失败时静默降级，核心数据正常保存

运动强度参考（METs）：
  - 步行      3.5 METs
  - 骑车      7.0 METs
  - 跑步      9.8 METs
  - 游泳      8.0 METs
  - 力量训练  5.0 METs
  - HIIT      12.0 METs
  - 瑜伽      2.5 METs
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, timedelta
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from src.core.config import settings
from src.models.health import HealthRecord, MetricType
from src.models.member import Member, Gender
from src.models.exercise import ExerciseType, WorkoutLog, WorkoutLogStatus

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上运动方案由 AI 生成，仅供参考，不构成医学诊断或康复处方。"
    "如有心血管疾病、骨关节损伤等慢性病，请在医生或运动康复师指导下执行。"
)

# MET 参考值
_MET_MAP = {
    ExerciseType.WALKING: 3.5,
    ExerciseType.CARDIO: 7.0,
    ExerciseType.STRENGTH: 5.0,
    ExerciseType.FLEXIBILITY: 2.5,
    ExerciseType.HIIT: 12.0,
    ExerciseType.SPORTS: 7.0,
    ExerciseType.SWIMMING: 8.0,
}


# ── 热量估算（METs 公式）────────────────────────────────────────────

def estimate_calories(exercise_type: ExerciseType, duration_minutes: int, weight_kg: float = 70.0) -> float:
    """
    热量(kcal) = MET × 体重(kg) × 时长(h)
    """
    met = _MET_MAP.get(exercise_type, 5.0)
    return round(met * weight_kg * (duration_minutes / 60.0), 1)


# ── 从 DB 聚合成员健康上下文 ─────────────────────────────────────────

async def _get_member_context(member: Member, db: AsyncSession) -> dict:
    """从健康记录抽取最新体重和身高"""
    from datetime import date as _date
    age = None
    if member.birth_date:
        today = _date.today()
        age = today.year - member.birth_date.year - (
            (today.month, today.day) < (member.birth_date.month, member.birth_date.day)
        )
    ctx = {
        "name": member.nickname,
        "age": age,
        "gender": (member.gender.value if hasattr(member.gender, "value") else member.gender) or "unknown",
        "weight_kg": 70.0,
        "height_cm": None,
    }
    for metric in (MetricType.WEIGHT, MetricType.HEIGHT):
        stmt = (
            select(HealthRecord)
            .where(HealthRecord.member_id == member.id, HealthRecord.metric_type == metric)
            .order_by(HealthRecord.measured_at.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row:
            if metric == MetricType.WEIGHT:
                ctx["weight_kg"] = row.value
            else:
                ctx["height_cm"] = row.value
    return ctx


def _safe_json(text: str | None, fallback):
    """安全解析 LLM 返回的 JSON，失败返回 fallback"""
    if not text:
        return fallback
    # 尝试提取 ```json ... ``` 代码块
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:]
            try:
                return json.loads(p.strip())
            except Exception:
                pass
    try:
        return json.loads(text)
    except Exception:
        return fallback


# ── LLM：生成运动计划 ────────────────────────────────────────────────

async def generate_fitness_plan(
    member: Member,
    db: AsyncSession,
    fitness_level: str,
    primary_goal: str,
    available_days: int,
    available_minutes: int,
    preferred_types: Optional[list] = None,
    limitations: Optional[list] = None,
    equipment: Optional[list] = None,
) -> dict:
    """
    返回 {
        week_plan: [...],   # 7天计划 JSON
        summary: str,       # LLM 整体说明
    }
    """
    ctx = await _get_member_context(member, db)

    prompt = f"""你是专业运动健身教练，请根据以下信息为用户制定**本周（7天）个性化运动计划**。

**用户信息**：
- 姓名：{ctx['name']}，年龄：{ctx['age']}，性别：{ctx['gender']}
- 体重：{ctx['weight_kg']} kg，身高：{ctx.get('height_cm', '未知')} cm
- 体能水平：{fitness_level}
- 主要目标：{primary_goal}
- 每周可运动天数：{available_days} 天
- 每次可用时间：{available_minutes} 分钟
- 偏好运动类型：{', '.join(preferred_types) if preferred_types else '无特别偏好'}
- 受伤/禁忌：{', '.join(limitations) if limitations else '无'}
- 可用器材：{', '.join(equipment) if equipment else '无（仅自重）'}

请返回如下 JSON，其中 rest=true 表示休息日，exercises 为当天训练列表：
```json
{{
  "week_plan": [
    {{
      "day": "周一",
      "rest": false,
      "theme": "下肢力量",
      "exercises": [
        {{
          "name": "深蹲",
          "type": "strength",
          "sets": 3,
          "reps": "12",
          "duration_min": 15,
          "calories_est": 80,
          "intensity": "中等",
          "tips": "膝盖不要超过脚尖"
        }}
      ]
    }}
  ],
  "summary": "本周计划说明（目标/进阶节奏/注意事项）"
}}
```"""

    default_plan = _make_default_plan(available_days, available_minutes, fitness_level)

    try:
        client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content or ""
        data = _safe_json(raw, default_plan)
        if not isinstance(data, dict) or "week_plan" not in data:
            data = default_plan
        data.setdefault("summary", "")
        if data.get("summary"):
            data["summary"] += DISCLAIMER
        return data
    except Exception as e:
        log.warning("LLM 生成运动计划失败，使用默认计划: %s", e)
        return default_plan


def _make_default_plan(available_days: int, available_minutes: int, fitness_level: str) -> dict:
    """无 LLM 时的基础运动计划（轻度有氧为主）"""
    all_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    # 均匀分配运动日（奇数位置）
    exercise_days = set()
    step = max(1, 7 // available_days)
    for i in range(0, 7, step):
        if len(exercise_days) < available_days:
            exercise_days.add(i)

    week_plan = []
    for idx, day in enumerate(all_days):
        if idx in exercise_days:
            week_plan.append({
                "day": day,
                "rest": False,
                "theme": "全身有氧",
                "exercises": [{
                    "name": "快走/慢跑",
                    "type": "cardio",
                    "sets": 1,
                    "reps": f"{available_minutes}分钟",
                    "duration_min": available_minutes,
                    "calories_est": round(estimate_calories(ExerciseType.CARDIO, available_minutes)),
                    "intensity": "低" if fitness_level in ("sedentary", "beginner") else "中等",
                    "tips": "保持心率在最大心率 60-70%",
                }],
            })
        else:
            week_plan.append({"day": day, "rest": True, "theme": "休息/拉伸", "exercises": []})
    return {
        "week_plan": week_plan,
        "summary": f"基础运动计划：每周 {available_days} 次有氧运动，每次约 {available_minutes} 分钟。" + DISCLAIMER,
    }


# ── LLM：分析运动日志并给出反馈 ─────────────────────────────────────

async def analyze_workout(
    exercise_type: ExerciseType,
    exercise_name: str,
    duration_minutes: int,
    weight_kg: float = 70.0,
    avg_heart_rate: Optional[int] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    返回 {
        calories_burned: float,
        llm_feedback: str,
    }
    """
    calories_est = estimate_calories(exercise_type, duration_minutes, weight_kg)

    hr_info = f"，平均心率 {avg_heart_rate} bpm" if avg_heart_rate else ""
    notes_info = f"，用户备注：{notes}" if notes else ""
    prompt = f"""用户刚完成一次运动：
- 运动项目：{exercise_name}（类型：{exercise_type.value}）
- 时长：{duration_minutes} 分钟{hr_info}
- 估算热量消耗：{calories_est} kcal{notes_info}

请给出简短的训练反馈（2-3 句话），包括：表现评价、恢复建议、下次训练提示。"""

    try:
        client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        feedback = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning("LLM 运动反馈失败: %s", e)
        feedback = f"完成 {exercise_name} {duration_minutes} 分钟，估算消耗 {calories_est} kcal。继续保持！"

    return {"calories_burned": calories_est, "llm_feedback": feedback}


# ── 每周运动汇总 ─────────────────────────────────────────────────────

async def get_weekly_summary(member_id, week_start: date, db: AsyncSession) -> dict:
    """聚合某周所有运动日志的统计数据"""
    week_end = week_start + timedelta(days=6)
    stmt = select(WorkoutLog).where(
        WorkoutLog.member_id == member_id,
        WorkoutLog.log_date >= week_start,
        WorkoutLog.log_date <= week_end,
    )
    logs = (await db.execute(stmt)).scalars().all()

    total_sessions = len(logs)
    completed = [l for l in logs if l.status == WorkoutLogStatus.COMPLETED]
    total_minutes = sum(l.duration_minutes or 0 for l in completed)
    total_calories = sum(l.calories_burned or 0.0 for l in completed)
    hr_values = [l.avg_heart_rate for l in completed if l.avg_heart_rate]
    avg_hr = round(sum(hr_values) / len(hr_values)) if hr_values else None

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_sessions": total_sessions,
        "completed_sessions": len(completed),
        "total_minutes": total_minutes,
        "total_calories": round(total_calories, 1),
        "avg_heart_rate": avg_hr,
    }
