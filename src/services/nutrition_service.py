"""
NutritionService — 个性化营养规划服务（T014）
=============================================
功能：
  1. 基于成员健康档案（年龄、体重、身高、疾病指标、用药）生成营养目标
  2. 按饮食类型 + 过敏原 + 禁忌，LLM 生成个性化每周食谱（7 天 × 3 餐 + 加餐）
  3. 饮食日志：自由文本描述，LLM 估算营养素并给出反馈
  4. 食物营养素数据库查询（内置 + 模糊搜索）
  5. LLM 调用失败时静默降级，核心数据（目标/日志）正常保存

营养目标计算基础（可被 LLM 进一步个性化）：
  - Harris-Benedict 公式计算 BMR
  - 活动系数（默认适度活动 × 1.55）
  - 宏营养素默认比例：蛋白质 20% / 脂肪 30% / 碳水 50%
"""
from __future__ import annotations

import json
import logging
import math
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.config import settings
from src.models.health import HealthRecord, MetricType
from src.models.member import Member, Gender
from src.models.medication import Medication, MedicationStatus

log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ 免责声明：以上营养建议由 AI 生成，仅供参考，不构成医学诊断或饮食处方。"
    "如有慢性病、特殊营养需求，请在专业营养师或医生指导下调整饮食。"
)


# ── 基础 BMR / TDEE 计算 ─────────────────────────────────────────────

def _calc_bmr(weight_kg: float, height_cm: float, age: int, gender: Optional[str]) -> float:
    """Harris-Benedict 修正公式"""
    if gender == "female":
        return 447.593 + 9.247 * weight_kg + 3.098 * height_cm - 4.330 * age
    return 88.362 + 13.397 * weight_kg + 4.799 * height_cm - 5.677 * age


def _default_goals(bmr: float) -> dict:
    """按 TDEE（适度活动 ×1.55）生成默认宏营养素目标（g）"""
    tdee = bmr * 1.55
    protein_cal = tdee * 0.20
    fat_cal = tdee * 0.30
    carb_cal = tdee * 0.50
    return {
        "daily_calories": round(tdee, 1),
        "daily_protein": round(protein_cal / 4, 1),
        "daily_fat": round(fat_cal / 9, 1),
        "daily_carbohydrate": round(carb_cal / 4, 1),
        "daily_fiber": 25.0,
        "daily_sodium": 2000.0,
    }


# ── 从 DB 聚合成员健康上下文 ─────────────────────────────────────────

async def _get_member_context(member: Member, db: AsyncSession) -> dict:
    """从健康记录提取最新的关键指标"""
    context: dict = {
        "name": member.name,
        "age": member.age,
        "gender": member.gender.value if member.gender else None,
        "weight_kg": None,
        "height_cm": None,
        "conditions": [],  # 根据指标异常推断潜在慢病
        "medications": [],
    }

    # 最新体重和身高
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
                context["weight_kg"] = row.value
            else:
                context["height_cm"] = row.value

    # 近期活跃用药
    meds_stmt = select(Medication).where(
        Medication.member_id == member.id,
        Medication.status == MedicationStatus.ACTIVE,
    )
    meds = (await db.execute(meds_stmt)).scalars().all()
    context["medications"] = [m.name for m in meds]

    return context


# ── LLM：生成营养目标 ────────────────────────────────────────────────

async def generate_nutrition_goal(
    member: Member,
    db: AsyncSession,
    diet_type: str = "normal",
    allergies: Optional[list] = None,
    dietary_restrictions: Optional[list] = None,
) -> dict:
    """
    返回 {
        daily_calories, daily_protein, daily_fat, daily_carbohydrate,
        daily_fiber, daily_sodium, llm_rationale
    }
    """
    ctx = await _get_member_context(member, db)

    # 先用公式算基础目标
    weight = ctx.get("weight_kg") or 65.0
    height = ctx.get("height_cm") or 170.0
    age = ctx.get("age") or 30
    gender = ctx.get("gender")
    bmr = _calc_bmr(weight, height, age, gender)
    defaults = _default_goals(bmr)

    system_prompt = """\
你是一位专业营养师 AI 助手。根据提供的成员健康信息，生成个性化每日营养目标。
严格按以下 JSON 格式输出（不输出其他内容）：
{
  "daily_calories": <数字，千卡>,
  "daily_protein": <数字，g>,
  "daily_fat": <数字，g>,
  "daily_carbohydrate": <数字，g>,
  "daily_fiber": <数字，g>,
  "daily_sodium": <数字，mg>,
  "rationale": "<2-3句话说明调整依据>"
}"""

    user_msg = f"""成员信息：
- 年龄：{age} 岁，性别：{gender or '未知'}
- 体重：{weight} kg，身高：{height} cm
- 饮食类型：{diet_type}
- 过敏原：{allergies or []}
- 饮食禁忌：{dietary_restrictions or []}
- 活跃用药：{ctx.get('medications') or []}
- BMR 基础计算结果（参考）：热量 {defaults['daily_calories']} kcal

请根据以上信息，结合饮食类型和特殊限制，给出调整后的营养目标。"""

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or ""
        data = _safe_json(raw)
        return {
            "daily_calories": data.get("daily_calories", defaults["daily_calories"]),
            "daily_protein": data.get("daily_protein", defaults["daily_protein"]),
            "daily_fat": data.get("daily_fat", defaults["daily_fat"]),
            "daily_carbohydrate": data.get("daily_carbohydrate", defaults["daily_carbohydrate"]),
            "daily_fiber": data.get("daily_fiber", defaults["daily_fiber"]),
            "daily_sodium": data.get("daily_sodium", defaults["daily_sodium"]),
            "llm_rationale": (data.get("rationale", "") + DISCLAIMER),
        }
    except Exception as e:
        log.warning("营养目标 LLM 失败，使用公式默认值: %s", e)
        return {**defaults, "llm_rationale": None}


# ── LLM：生成每周食谱 ────────────────────────────────────────────────

async def generate_meal_plan(
    member: Member,
    db: AsyncSession,
    diet_type: str,
    allergies: Optional[list],
    dietary_restrictions: Optional[list],
    daily_calories: float,
) -> dict:
    """
    返回 {
        plan_data: JSON str（7天食谱），
        llm_summary: str
    }
    """
    ctx = await _get_member_context(member, db)
    age = ctx.get("age") or 30
    meds = ctx.get("medications") or []

    allergy_str = "、".join(allergies) if allergies else "无"
    restriction_str = "、".join(dietary_restrictions) if dietary_restrictions else "无"
    med_str = "、".join(meds) if meds else "无"

    system_prompt = """\
你是一位专业营养师 AI 助手。请生成一份科学合理的个性化 7 天食谱。
严格按以下 JSON 格式输出（不输出其他内容）：
[
  {
    "day": "周一",
    "meals": [
      {"type": "breakfast", "dishes": ["食物1", "食物2"], "calories": 数字, "tips": "简短饮食小贴士"},
      {"type": "lunch",     "dishes": ["食物1", "食物2"], "calories": 数字, "tips": ""},
      {"type": "dinner",    "dishes": ["食物1", "食物2"], "calories": 数字, "tips": ""},
      {"type": "snack",     "dishes": ["食物1"],           "calories": 数字, "tips": ""}
    ]
  },
  ...（共 7 天）
]"""

    user_msg = f"""成员信息：
- 年龄：{age} 岁，饮食类型：{diet_type}
- 每日热量目标：{daily_calories} 千卡
- 过敏原（严格避开）：{allergy_str}
- 饮食禁忌：{restriction_str}
- 当前用药（注意食药相互作用）：{med_str}

请生成符合中国饮食习惯、食材易获取、营养均衡的 7 天食谱。"""

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=2000,
            temperature=0.5,
        )
        raw = resp.choices[0].message.content or ""
        # 解析 JSON 数组
        import re
        try:
            plan = json.loads(raw.strip())
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            plan = json.loads(match.group()) if match else []

        summary = f"已为您生成本周{diet_type}食谱，每日约 {daily_calories:.0f} 千卡。" + DISCLAIMER
        return {
            "plan_data": json.dumps(plan, ensure_ascii=False),
            "llm_summary": summary,
        }
    except Exception as e:
        log.warning("食谱生成 LLM 失败: %s", e)
        return {
            "plan_data": None,
            "llm_summary": "食谱生成暂时不可用，请稍后重试。" + DISCLAIMER,
        }


# ── LLM：饮食日志营养估算 + 反馈 ─────────────────────────────────────

async def analyze_diet_log(description: str, meal_type: str) -> dict:
    """
    输入：用户自由文本描述（如"吃了一碗燕麦粥加一个鸡蛋"）
    返回：{
        estimated_calories, estimated_protein, estimated_fat,
        estimated_carbohydrate, llm_feedback
    }
    """
    system_prompt = """\
你是专业营养分析 AI。根据用户描述的饮食内容，估算营养摄入量并给出健康反馈。
严格按以下 JSON 格式输出（不输出其他内容）：
{
  "estimated_calories": <数字，千卡，可为 null>,
  "estimated_protein": <数字，g，可为 null>,
  "estimated_fat": <数字，g，可为 null>,
  "estimated_carbohydrate": <数字，g，可为 null>,
  "feedback": "<1-2句健康提示或改善建议>"
}"""

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"餐次：{meal_type}\n描述：{description}"},
            ],
            max_tokens=300,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or ""
        data = _safe_json(raw)
        return {
            "estimated_calories": data.get("estimated_calories"),
            "estimated_protein": data.get("estimated_protein"),
            "estimated_fat": data.get("estimated_fat"),
            "estimated_carbohydrate": data.get("estimated_carbohydrate"),
            "llm_feedback": (data.get("feedback", "") + DISCLAIMER) if data.get("feedback") else None,
        }
    except Exception as e:
        log.warning("饮食日志 LLM 分析失败，静默降级: %s", e)
        return {
            "estimated_calories": None,
            "estimated_protein": None,
            "estimated_fat": None,
            "estimated_carbohydrate": None,
            "llm_feedback": None,
        }


# ── 工具函数 ─────────────────────────────────────────────────────────

def _safe_json(raw: str) -> dict:
    import re
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}
