"""
SymptomService — 症状日记 NLP 分析服务（T011）
===============================================
流程：
  1. 接收用户自由描述文本
  2. LLM 结构化提取症状（名称/部位/程度/持续时间/性质）
  3. 评估严重度分值（1-10）及就医建议等级
  4. 生成通俗总结（含免责声明）
  5. LLM 失败时静默降级，原始文本正常保存

就医建议等级定义：
  1-3  → self_care   （自愈观察）
  4-5  → monitor     （密切观察）
  6-7  → visit_soon  （尽快就医）
  8-10 → emergency   （紧急就医）
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

ADVICE_MAP = {
    range(1, 4): "self_care",
    range(4, 6): "monitor",
    range(6, 8): "visit_soon",
    range(8, 11): "emergency",
}


def _score_to_advice(score: int) -> str:
    for r, lvl in ADVICE_MAP.items():
        if score in r:
            return lvl
    return "monitor"


class SymptomService:
    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    async def analyze(self, raw_text: str) -> dict:
        """
        调用 LLM 分析症状描述，返回：
          structured_symptoms: str (JSON)
          severity_score: int
          advice_level: str
          llm_summary: str

        任何步骤失败均静默降级，返回 None 值。
        """
        prompt = f"""你是一位经验丰富的家庭医生助手，请分析以下症状描述，以 JSON 格式返回结构化信息。

症状描述：「{raw_text}」

请返回如下 JSON（严格遵守格式，不要加注释）：
{{
  "symptoms": [
    {{
      "name": "症状名称",
      "severity": "程度描述（轻微/中度/剧烈）或 null",
      "location": "发生部位或 null",
      "duration": "持续时间或 null",
      "character": "性质描述（如搏动性/持续性/阵发性）或 null"
    }}
  ],
  "severity_score": <1-10的整数，1=非常轻微，10=危及生命>,
  "summary": "50字以内的通俗总结，指出最重要的症状和建议",
  "disclaimer": "本分析仅供参考，不构成诊断意见，如有不适请及时就医。"
}}

评分参考：
  1-3 = 轻微不适，可自愈观察
  4-5 = 需密切观察，适当休息
  6-7 = 建议近期就医
  8-10 = 需紧急就医（如胸痛/呼吸困难/意识障碍等危险症状）"""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=800,
            )
            raw = resp.choices[0].message.content
            data = json.loads(raw)
        except Exception as exc:
            log.warning("LLM 症状分析失败，静默降级: %s", exc)
            return {
                "structured_symptoms": None,
                "severity_score": None,
                "advice_level": None,
                "llm_summary": None,
            }

        # 提取 severity_score 并推断 advice_level
        score = data.get("severity_score")
        if not isinstance(score, int) or not (1 <= score <= 10):
            score = None
        advice = _score_to_advice(score) if score else None

        # 序列化 structured_symptoms
        symptoms = data.get("symptoms", [])
        symptoms_json = json.dumps(symptoms, ensure_ascii=False) if symptoms else None

        # 拼接摘要 + 免责
        summary_text = data.get("summary", "")
        disclaimer = data.get("disclaimer", "本分析仅供参考，不构成诊断意见，如有不适请及时就医。")
        llm_summary = f"{summary_text}\n\n{disclaimer}" if summary_text else None

        return {
            "structured_symptoms": symptoms_json,
            "severity_score": score,
            "advice_level": advice,
            "llm_summary": llm_summary,
        }
