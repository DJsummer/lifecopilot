"""
ReportService — 家庭健康周报/月报生成服务（T018）
=================================================
流程：
  1. 聚合指定周期内的 HealthRecord（按指标分组计算 avg/min/max/count/trend）
  2. 聚合 AdherenceLog（计算每种药物的依从性）
  3. 提取异常事件（超出正常值域的记录）
  4. 调用 LLM 生成自然语言总结报告
  5. LLM 失败时静默降级（stats 正常保存，llm_summary=None）
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Dict, List, Optional

from openai import AsyncOpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# ── 各指标正常值域（用于 notable_events 检测）────────────────────────────
NORMAL_RANGES: Dict[str, tuple] = {
    "blood_pressure_sys": (90.0, 140.0),
    "blood_pressure_dia": (60.0, 90.0),
    "heart_rate": (60.0, 100.0),
    "blood_glucose": (3.9, 7.8),
    "body_temperature": (36.0, 37.3),
    "spo2": (95.0, 100.0),
    "sleep_hours": (7.0, 9.0),
}

# 各指标单位
METRIC_UNITS: Dict[str, str] = {
    "blood_pressure_sys": "mmHg",
    "blood_pressure_dia": "mmHg",
    "heart_rate": "bpm",
    "blood_glucose": "mmol/L",
    "weight": "kg",
    "height": "cm",
    "body_temperature": "°C",
    "spo2": "%",
    "steps": "步",
    "sleep_hours": "h",
}


class ReportService:
    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    # ── 指标统计 ─────────────────────────────────────────────────────

    def compute_metric_stats(self, records: list) -> List[dict]:
        """按 metric_type 分组计算 avg/min/max/count/trend/latest"""
        grouped: Dict[str, list] = {}
        for r in records:
            grouped.setdefault(r.metric_type if isinstance(r.metric_type, str) else r.metric_type.value, []).append(r)

        stats = []
        for metric, recs in grouped.items():
            values = [r.value for r in recs]
            # 按时间排序
            sorted_recs = sorted(recs, key=lambda x: x.measured_at)
            sorted_vals = [r.value for r in sorted_recs]
            n = len(sorted_vals)
            trend = "数据不足"
            if n >= 4:
                first_half_avg = sum(sorted_vals[: n // 2]) / (n // 2)
                second_half_avg = sum(sorted_vals[n // 2 :]) / (n - n // 2)
                diff = second_half_avg - first_half_avg
                if abs(diff) < 0.03 * first_half_avg:
                    trend = "平稳"
                elif diff > 0:
                    trend = "上升"
                else:
                    trend = "下降"
            stats.append(
                {
                    "metric_type": metric,
                    "unit": METRIC_UNITS.get(metric, ""),
                    "count": n,
                    "avg": round(sum(values) / n, 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                    "trend": trend,
                    "latest": round(sorted_vals[-1], 2),
                }
            )
        return stats

    # ── 用药依从性统计 ───────────────────────────────────────────────

    def compute_medication_stats(self, medications: list, adherence_logs: list) -> List[dict]:
        """计算每种药物在报告周期内的依从性"""
        log_by_med: Dict[str, list] = {}
        for al in adherence_logs:
            mid = str(al.medication_id)
            log_by_med.setdefault(mid, []).append(al)

        stats = []
        for med in medications:
            mid = str(med.id)
            logs = log_by_med.get(mid, [])
            total = len(logs)
            taken = sum(
                1 for al in logs
                if (al.status if isinstance(al.status, str) else al.status.value) == "taken"
            )
            stats.append(
                {
                    "name": med.name,
                    "total_logs": total,
                    "taken": taken,
                    "adherence_rate": round(taken / total, 3) if total else 0.0,
                }
            )
        return stats

    # ── 异常事件提取 ─────────────────────────────────────────────────

    def extract_notable_events(self, records: list) -> List[dict]:
        """返回超出正常范围的记录"""
        events = []
        for r in records:
            metric = r.metric_type if isinstance(r.metric_type, str) else r.metric_type.value
            if metric not in NORMAL_RANGES:
                continue
            lo, hi = NORMAL_RANGES[metric]
            if r.value < lo:
                direction = "偏低"
            elif r.value > hi:
                direction = "偏高"
            else:
                continue
            events.append(
                {
                    "metric_type": metric,
                    "value": r.value,
                    "unit": METRIC_UNITS.get(metric, ""),
                    "measured_at": r.measured_at.isoformat(),
                    "direction": direction,
                }
            )
        return events

    # ── LLM 总结生成 ─────────────────────────────────────────────────

    def _format_metric_stats_text(self, stats: List[dict]) -> str:
        lines = []
        for s in stats:
            lines.append(
                f"  · {s['metric_type']}：{s['count']} 次，"
                f"均值 {s['avg']}{s['unit']}，"
                f"范围 [{s['min']} – {s['max']}]，趋势：{s['trend']}"
            )
        return "\n".join(lines) if lines else "  （本周期无记录）"

    def _format_medication_stats_text(self, stats: List[dict]) -> str:
        lines = []
        for s in stats:
            rate_pct = round(s["adherence_rate"] * 100)
            lines.append(
                f"  · {s['name']}：{s['total_logs']} 次计划，"
                f"已服 {s['taken']} 次（依从率 {rate_pct}%）"
            )
        return "\n".join(lines) if lines else "  （无用药记录）"

    def _format_events_text(self, events: List[dict]) -> str:
        if not events:
            return "  （无异常事件）"
        lines = [
            f"  · {e['measured_at'][:10]} {e['metric_type']} {e['value']}{e['unit']}（{e['direction']}）"
            for e in events[:10]  # 最多展示 10 条
        ]
        return "\n".join(lines)

    async def generate_llm_summary(
        self,
        member_nickname: str,
        member_role: str,
        period_type: str,
        period_start: date,
        period_end: date,
        metric_stats: List[dict],
        medication_stats: List[dict],
        notable_events: List[dict],
    ) -> Optional[str]:
        """调用 LLM 生成自然语言总结，失败时返回 None"""
        period_label = "周报" if period_type == "weekly" else "月报"
        role_hint = {
            "elder": "老人，请使用大字体友好、通俗的语言",
            "child": "儿童，请使用家长易懂的表述关注生长发育",
            "admin": "家庭管理员",
            "adult": "成人",
        }.get(member_role, "成人")

        prompt = f"""你是家庭健康助手 LifePilot，请为以下成员生成一份{period_label}健康总结。

成员：{member_nickname}（{role_hint}）
统计周期：{period_start} 至 {period_end}

【健康指标统计】
{self._format_metric_stats_text(metric_stats)}

【用药依从情况】
{self._format_medication_stats_text(medication_stats)}

【异常事件（共 {len(notable_events)} 次）】
{self._format_events_text(notable_events)}

请生成一份简洁的健康总结，包括：
1. 整体健康状况评价
2. 各项指标的变化趋势分析
3. 需要重点关注的问题
4. 具体可行的健康建议

要求：通俗易懂，不超过 500 字。
最后附上：本报告仅供参考，不构成医疗建议，如有不适请及时就医获取专业诊断。"""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=800,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            log.warning("LLM 报告生成失败，静默降级: %s", exc)
            return None

    # ── 主方法 ───────────────────────────────────────────────────────

    async def generate_report(
        self,
        member,
        records: list,
        medications: list,
        adherence_logs: list,
        period_type: str,
        period_start: date,
        period_end: date,
    ) -> dict:
        """
        生成报告数据字典：
          metric_stats / medication_stats / notable_events / llm_summary / status
        """
        metric_stats = self.compute_metric_stats(records)
        medication_stats = self.compute_medication_stats(medications, adherence_logs)
        notable_events = self.extract_notable_events(records)

        llm_summary = await self.generate_llm_summary(
            member_nickname=member.nickname,
            member_role=member.role if isinstance(member.role, str) else member.role.value,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            metric_stats=metric_stats,
            medication_stats=medication_stats,
            notable_events=notable_events,
        )

        return {
            "metric_stats": json.dumps(metric_stats, ensure_ascii=False),
            "medication_stats": json.dumps(medication_stats, ensure_ascii=False),
            "notable_events": json.dumps(notable_events, ensure_ascii=False),
            "llm_summary": llm_summary,
            "status": "done",
        }
