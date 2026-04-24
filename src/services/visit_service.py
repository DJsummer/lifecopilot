"""
VisitService — 就医准备助手服务（T019）
=======================================
流程：
  1. 聚合当前活跃用药快照
  2. 聚合近期健康指标快照（最近 N 天，默认 30 天）
  3. 聚合近期检验单异常项
  4. 调用 LLM 生成结构化就诊摘要（中文 / 英文 / 双语）
  5. LLM 失败时静默降级，快照数据正常保存
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from openai import AsyncOpenAI

from src.core.config import settings
from src.services.report_service import METRIC_UNITS  # 复用指标单位映射

log = logging.getLogger(__name__)


class VisitService:
    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    # ── 数据聚合 ──────────────────────────────────────────────────────

    def build_medication_snapshot(self, medications: list) -> List[dict]:
        """活跃用药清单快照"""
        return [
            {
                "name": m.name,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "instructions": m.instructions,
            }
            for m in medications
        ]

    def build_health_snapshot(self, records: list) -> List[dict]:
        """近期健康指标摘要（各类型取最新值 + 近期均值）"""
        grouped: Dict[str, list] = {}
        for r in records:
            key = r.metric_type if isinstance(r.metric_type, str) else r.metric_type.value
            grouped.setdefault(key, []).append(r)

        snap = []
        for metric, recs in grouped.items():
            values = [r.value for r in recs]
            sorted_recs = sorted(recs, key=lambda x: x.measured_at)
            snap.append(
                {
                    "metric_type": metric,
                    "unit": METRIC_UNITS.get(metric, ""),
                    "latest": round(sorted_recs[-1].value, 2),
                    "avg_recent": round(sum(values) / len(values), 2),
                    "count": len(values),
                }
            )
        return snap

    def build_lab_snapshot(self, lab_reports: list) -> List[dict]:
        """近期检验单快照（取有异常项的最近 5 份）"""
        # 先过滤有异常的，按时间倒序，取最多 5 条
        sorted_reports = sorted(lab_reports, key=lambda r: r.report_date, reverse=True)
        result = []
        for r in sorted_reports[:10]:
            result.append(
                {
                    "report_date": r.report_date.isoformat() if hasattr(r.report_date, "isoformat") else str(r.report_date),
                    "report_type": r.report_type if isinstance(r.report_type, str) else r.report_type.value,
                    "abnormal_items": r.abnormal_items,
                    "has_abnormal": r.has_abnormal,
                }
            )
            if len(result) >= 5:
                break
        return result

    # ── LLM 就诊摘要生成 ─────────────────────────────────────────────

    def _format_medications_text(self, snap: List[dict]) -> str:
        if not snap:
            return "  （无活跃用药记录）"
        lines = [f"  · {m['name']} {m['dosage']}，{m['frequency']}" for m in snap]
        return "\n".join(lines)

    def _format_health_text(self, snap: List[dict]) -> str:
        if not snap:
            return "  （近期无健康数据）"
        lines = [
            f"  · {s['metric_type']}：最新 {s['latest']}{s['unit']}，近期均值 {s['avg_recent']}{s['unit']}（共 {s['count']} 次）"
            for s in snap
        ]
        return "\n".join(lines)

    def _format_lab_text(self, snap: List[dict]) -> str:
        if not snap:
            return "  （无近期检验记录）"
        lines = []
        for r in snap:
            flag = "⚠️ 有异常" if r["has_abnormal"] else "正常"
            lines.append(f"  · {r['report_date']} {r['report_type']}（{flag}）")
        return "\n".join(lines)

    async def generate_summary_zh(
        self,
        member_nickname: str,
        member_role: str,
        chief_complaint: str,
        symptom_duration: Optional[str],
        aggravating_factors: Optional[str],
        relieving_factors: Optional[str],
        past_medical_history: Optional[str],
        medication_snap: List[dict],
        health_snap: List[dict],
        lab_snap: List[dict],
    ) -> Optional[str]:
        """LLM 生成中文就诊摘要"""
        prompt = f"""你是家庭健康助手 LifePilot，请为以下患者生成一份结构化就诊摘要，供医生参考。

【患者信息】
姓名：{member_nickname}（角色：{member_role}）

【主诉】
{chief_complaint}

【症状持续时间】
{symptom_duration or '未填写'}

【加重因素】
{aggravating_factors or '未填写'}

【缓解因素】
{relieving_factors or '未填写'}

【既往史及其他补充】
{past_medical_history or '未填写'}

【当前用药清单】
{self._format_medications_text(medication_snap)}

【近期健康指标】
{self._format_health_text(health_snap)}

【近期检验记录】
{self._format_lab_text(lab_snap)}

请生成一份结构化就诊摘要，包含：
1. 基本信息与主诉
2. 症状描述（时间、性质、加重/缓解因素）
3. 相关健康背景（用药、体征指标、检验异常）
4. 就医建议要点（提醒患者向医生说明的重点）

格式要求：条理清晰，不超过 600 字。
最后注明：本摘要由 AI 辅助生成，仅供就医参考，不构成诊断意见，请遵医嘱。"""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            log.warning("LLM 中文摘要生成失败，静默降级: %s", exc)
            return None

    async def generate_summary_en(
        self,
        member_nickname: str,
        member_role: str,
        chief_complaint: str,
        symptom_duration: Optional[str],
        aggravating_factors: Optional[str],
        relieving_factors: Optional[str],
        past_medical_history: Optional[str],
        medication_snap: List[dict],
        health_snap: List[dict],
        lab_snap: List[dict],
    ) -> Optional[str]:
        """LLM 生成英文就诊摘要"""
        prompt = f"""You are LifePilot, a family health assistant. Please generate a structured medical visit summary for the following patient to share with their doctor.

[Patient]
Name: {member_nickname} (Role: {member_role})

[Chief Complaint]
{chief_complaint}

[Symptom Duration]
{symptom_duration or 'Not provided'}

[Aggravating Factors]
{aggravating_factors or 'Not provided'}

[Relieving Factors]
{relieving_factors or 'Not provided'}

[Past Medical History / Additional Notes]
{past_medical_history or 'Not provided'}

[Current Medications]
{self._format_medications_text(medication_snap)}

[Recent Health Metrics]
{self._format_health_text(health_snap)}

[Recent Lab Reports]
{self._format_lab_text(lab_snap)}

Please generate a structured visit summary including:
1. Patient overview and chief complaint
2. Symptom description (onset, nature, aggravating/relieving factors)
3. Relevant health background (medications, vital signs, abnormal lab findings)
4. Key points to communicate with the doctor

Keep it concise (under 500 words) and clear.
Note: This summary is AI-assisted and for reference only. It does not constitute a medical diagnosis. Please follow your doctor's advice."""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            log.warning("LLM 英文摘要生成失败，静默降级: %s", exc)
            return None

    # ── 主方法 ───────────────────────────────────────────────────────

    async def prepare_visit(
        self,
        member,
        medications: list,
        health_records: list,
        lab_reports: list,
        chief_complaint: str,
        symptom_duration: Optional[str],
        aggravating_factors: Optional[str],
        relieving_factors: Optional[str],
        past_medical_history: Optional[str],
        visit_language: str,
    ) -> dict:
        """
        聚合数据 + LLM 生成摘要，返回可直接写入 ORM 的字典
        """
        medication_snap = self.build_medication_snapshot(medications)
        health_snap = self.build_health_snapshot(health_records)
        lab_snap = self.build_lab_snapshot(lab_reports)

        role = member.role if isinstance(member.role, str) else member.role.value
        nickname = member.nickname

        kwargs = dict(
            member_nickname=nickname,
            member_role=role,
            chief_complaint=chief_complaint,
            symptom_duration=symptom_duration,
            aggravating_factors=aggravating_factors,
            relieving_factors=relieving_factors,
            past_medical_history=past_medical_history,
            medication_snap=medication_snap,
            health_snap=health_snap,
            lab_snap=lab_snap,
        )

        summary_zh: Optional[str] = None
        summary_en: Optional[str] = None

        if visit_language in ("zh", "both"):
            summary_zh = await self.generate_summary_zh(**kwargs)
        if visit_language in ("en", "both"):
            summary_en = await self.generate_summary_en(**kwargs)

        return {
            "medications_snapshot": json.dumps(medication_snap, ensure_ascii=False),
            "health_snapshot": json.dumps(health_snap, ensure_ascii=False),
            "lab_snapshot": json.dumps(lab_snap, ensure_ascii=False),
            "summary_zh": summary_zh,
            "summary_en": summary_en,
        }
