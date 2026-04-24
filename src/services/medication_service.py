"""
MedicationService — 用药管理 AI 服务（T020）
==========================================
功能：
  1. LLM 通俗解释药物作用与常见副作用
  2. LLM 多药物相互作用风险检查
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# ── LLM Prompts ───────────────────────────────────────────────────────

_EXPLAIN_SYSTEM = """你是一位经验丰富的临床药师，擅长用患者能理解的语言解释药物信息。
请根据提供的药品名称和剂量，用通俗中文向患者解释：
1. 这个药主要用来治疗什么
2. 主要的药理作用机制（用简单语言）
3. 常见副作用（列出最重要的3-5项）
4. 服用注意事项（饭前/饭后、是否可掰开、避免同服的食物等）
5. 漏服了怎么办

输出严格 JSON 格式：
{
  "indication": "主要适应症（一句话）",
  "mechanism": "作用机制（通俗描述）",
  "common_side_effects": ["副作用1", "副作用2", "副作用3"],
  "instructions": "服用注意事项",
  "missed_dose_advice": "漏服建议",
  "disclaimer": "本说明仅供参考，请遵医嘱用药，不可自行增减剂量。"
}"""

_EXPLAIN_USER_TMPL = "药品：{name}，剂量：{dosage}。请输出 JSON，不要任何额外文字。"


_INTERACTION_SYSTEM = """你是一位临床药学专家，专门负责审查多药物联合使用的安全性。
请分析以下药物之间的相互作用风险，输出严格 JSON：
{
  "has_interaction": true/false,
  "risk_level": "none/low/moderate/high/critical",
  "interactions": [
    {
      "drug_a": "药物A",
      "drug_b": "药物B",
      "mechanism": "相互作用机制",
      "consequence": "可能的临床后果",
      "severity": "low/moderate/high/critical",
      "management": "处理建议"
    }
  ],
  "summary": "整体风险概述（1-2句话）",
  "advice": "给患者的具体建议",
  "disclaimer": "本分析仅供参考，请告知医生或药师您正在服用的所有药物。"
}
risk_level 规则：none=无相互作用，low=轻微注意，moderate=需监测，high=避免联用，critical=禁止联用"""

_INTERACTION_USER_TMPL = "请分析以下药物的相互作用：{medications}。输出 JSON，不要额外文字。"


class MedicationService:
    """用药管理 AI 服务"""

    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        self._openai = openai_client or AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    async def explain_medication(self, name: str, dosage: str) -> dict:
        """
        用 LLM 生成药物通俗说明。
        返回字段：indication / mechanism / common_side_effects /
                  instructions / missed_dose_advice / disclaimer
        """
        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _EXPLAIN_SYSTEM},
                {"role": "user", "content": _EXPLAIN_USER_TMPL.format(name=name, dosage=dosage)},
            ],
            temperature=0.1,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("explain_medication: invalid JSON for %s, raw=%s", name, raw[:100])
            result = {
                "indication": f"{name} 的适应症",
                "mechanism": "请咨询医生或药师",
                "common_side_effects": [],
                "instructions": "请严格遵医嘱服用",
                "missed_dose_advice": "漏服后请咨询医生",
                "disclaimer": "本说明仅供参考，请遵医嘱用药。",
            }
        result.setdefault("disclaimer", "本说明仅供参考，请遵医嘱用药，不可自行增减剂量。")
        log.info("medication explained", name=name)
        return result

    def format_description(self, llm_result: dict) -> str:
        """
        将 LLM 解释结果转为适合存储在 llm_description 字段的纯文本。
        """
        parts = []
        if llm_result.get("indication"):
            parts.append(f"【适应症】{llm_result['indication']}")
        if llm_result.get("mechanism"):
            parts.append(f"【作用机制】{llm_result['mechanism']}")
        effects = llm_result.get("common_side_effects") or []
        if effects:
            parts.append("【常见副作用】" + "；".join(effects))
        if llm_result.get("instructions"):
            parts.append(f"【服用注意】{llm_result['instructions']}")
        if llm_result.get("missed_dose_advice"):
            parts.append(f"【漏服建议】{llm_result['missed_dose_advice']}")
        parts.append(llm_result.get("disclaimer", "本说明仅供参考，请遵医嘱用药。"))
        return "\n\n".join(parts)

    async def check_interactions(self, medication_names: List[str]) -> dict:
        """
        检查多种药物的相互作用风险。
        返回字段：has_interaction / risk_level / interactions / summary / advice / disclaimer
        """
        meds_str = "、".join(medication_names)
        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _INTERACTION_SYSTEM},
                {"role": "user", "content": _INTERACTION_USER_TMPL.format(medications=meds_str)},
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("check_interactions: invalid JSON, raw=%s", raw[:100])
            result = {
                "has_interaction": False,
                "risk_level": "none",
                "interactions": [],
                "summary": "无法完成分析，请咨询专业药师",
                "advice": "请将所有用药信息告知医生或药师",
                "disclaimer": "本分析仅供参考，请告知医生或药师您正在服用的所有药物。",
            }
        result.setdefault(
            "disclaimer", "本分析仅供参考，请告知医生或药师您正在服用的所有药物。"
        )
        log.info(
            "interaction checked",
            medications=medication_names,
            risk=result.get("risk_level"),
        )
        return result
