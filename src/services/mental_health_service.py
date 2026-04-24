"""
MentalHealthService — 心理健康筛查服务（T016）
================================================
功能：
  1. PHQ-9 抑郁自评量表评分（0-27）及风险等级
  2. GAD-7 广泛性焦虑量表评分（0-21）及风险等级
  3. LLM 情绪日记 NLP 分析：情感倾向、情绪波动摘要、心理健康建议
  4. 综合风险判定（取 PHQ-9 / GAD-7 / NLP 评估的最高等级）
  5. 推荐干预资源（随风险等级升级）
  6. LLM 失败时静默降级，量表评分不受影响

风险等级定义：
  PHQ-9:  0-4→low  5-9→moderate  10-14→high  15-27→crisis
  GAD-7:  0-4→low  5-9→moderate  10-14→high  15-21→crisis
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# ── 风险等级权重（用于比较最大风险）────────────────────────────────────────
RISK_WEIGHT: Dict[str, int] = {
    "low": 0,
    "moderate": 1,
    "high": 2,
    "crisis": 3,
}

# ── PHQ-9 评分区间 ────────────────────────────────────────────────────────
PHQ9_RANGES = [
    (range(0, 5), "low"),
    (range(5, 10), "moderate"),
    (range(10, 15), "high"),
    (range(15, 28), "crisis"),
]

# ── GAD-7 评分区间 ────────────────────────────────────────────────────────
GAD7_RANGES = [
    (range(0, 5), "low"),
    (range(5, 10), "moderate"),
    (range(10, 15), "high"),
    (range(15, 22), "crisis"),
]

# ── 推荐资源（随风险升级） ────────────────────────────────────────────────
RESOURCES_MAP: Dict[str, List[str]] = {
    "low": [
        "每天保持适量运动，建议 30 分钟有氧运动",
        "正念冥想 App：潮汐 / Headspace / 冥想星球",
        "保持规律作息，睡眠是最好的心理修复",
    ],
    "moderate": [
        "尝试正念冥想或深呼吸练习（每天 10 分钟）",
        "与信任的朋友或家人倾诉你的感受",
        "推荐阅读：《伯恩斯新情绪疗法》",
        "如持续超过两周，建议预约心理咨询师",
    ],
    "high": [
        "建议尽快预约心理咨询师或精神科医生",
        "全国心理援助热线：400-161-9995（24 小时）",
        "北京心理危机研究与干预中心：010-82951332",
        "告知身边信任的家人或朋友你的状态",
    ],
    "crisis": [
        "请立即联系家人或监护人",
        "全国心理危机干预热线：400-800-1030（24 小时）",
        "如有自伤或伤人危险，请立即拨打急救：120",
        "如实告诉医生你的想法，寻求专业帮助",
    ],
}


def score_phq9(answers: List[int]) -> tuple[int, str]:
    """计算 PHQ-9 总分及风险等级，答案长度必须为 9，每项 0-3"""
    total = sum(answers)
    for r, level in PHQ9_RANGES:
        if total in r:
            return total, level
    return total, "crisis"


def score_gad7(answers: List[int]) -> tuple[int, str]:
    """计算 GAD-7 总分及风险等级，答案长度必须为 7，每项 0-3"""
    total = sum(answers)
    for r, level in GAD7_RANGES:
        if total in r:
            return total, level
    return total, "crisis"


def combine_risk(levels: List[str]) -> str:
    """取多个风险等级中的最高值"""
    if not levels:
        return "low"
    return max(levels, key=lambda lvl: RISK_WEIGHT.get(lvl, 0))


def get_resources(risk_level: str) -> List[str]:
    return RESOURCES_MAP.get(risk_level, RESOURCES_MAP["low"])


class MentalHealthService:
    """心理健康筛查服务"""

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    async def analyze_emotion(
        self,
        emotion_text: str,
        emotion_tags: Optional[List[str]] = None,
    ) -> Dict:
        """
        LLM 分析情绪日记文本。
        返回：
          {
            "mood_score": 1-10,          # 1=极度低落, 10=非常愉快
            "detected_tags": [...],       # 检测到的情绪标签
            "nlp_analysis": "...",        # 自然语言分析
            "risk_hint": "low|moderate|high|crisis"  # NLP 层面的风险提示
          }
        LLM 失败时返回全 None 字典，不抛出异常。
        """
        tags_hint = ""
        if emotion_tags:
            tags_hint = f"\n用户已标记的情绪标签：{', '.join(emotion_tags)}"

        prompt = f"""你是一位专业的心理健康评估助手。请分析以下情绪日记，用中文回答，输出 JSON 格式。

情绪日记内容：
{emotion_text}{tags_hint}

请输出以下 JSON（仅输出 JSON，不要其他内容）：
{{
  "mood_score": <整数 1-10，1=极度低落/痛苦，5=一般，10=非常愉快积极>,
  "detected_tags": [<检测到的情绪标签，如"焦虑"、"悲伤"、"孤独"等，最多 5 个>],
  "nlp_analysis": "<100-150 字的情感分析，包含情绪状态描述和简短心理健康建议>",
  "risk_hint": "<基于内容判断的风险提示：low / moderate / high / crisis>"
}}

注意：
- risk_hint 为 high 或 crisis 时，nlp_analysis 应包含建议寻求专业帮助的内容
- 如果文本提到自伤、自杀或伤害他人，risk_hint 必须为 crisis"""

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            data = json.loads(raw)

            mood_score = int(data.get("mood_score", 5))
            mood_score = max(1, min(10, mood_score))

            detected_tags = data.get("detected_tags") or []
            nlp_analysis = data.get("nlp_analysis", "")
            risk_hint = data.get("risk_hint", "low")
            if risk_hint not in RISK_WEIGHT:
                risk_hint = "low"

            return {
                "mood_score": mood_score,
                "detected_tags": detected_tags,
                "nlp_analysis": nlp_analysis,
                "risk_hint": risk_hint,
            }
        except Exception as exc:
            log.warning("情绪分析 LLM 调用失败，静默降级", exc_info=exc)
            return {
                "mood_score": None,
                "detected_tags": emotion_tags or [],
                "nlp_analysis": None,
                "risk_hint": "low",
            }
