"""T018：家庭健康周报/月报 API 集成测试"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.report import _get_service
from src.services.report_service import ReportService

pytestmark = [pytest.mark.integration, pytest.mark.report]

# ── mock 数据 ─────────────────────────────────────────────────────────

FAKE_METRIC_STATS = [
    {
        "metric_type": "blood_pressure_sys",
        "unit": "mmHg",
        "count": 7,
        "avg": 126.4,
        "min": 118.0,
        "max": 138.0,
        "trend": "平稳",
        "latest": 125.0,
    }
]

FAKE_MED_STATS = [
    {
        "name": "苯磺酸氨氯地平",
        "total_logs": 14,
        "taken": 12,
        "adherence_rate": 0.857,
    }
]

FAKE_EVENTS = [
    {
        "metric_type": "blood_pressure_sys",
        "value": 138.0,
        "unit": "mmHg",
        "measured_at": "2026-04-20T08:00:00+00:00",
        "direction": "偏高",
    }
]

FAKE_SUMMARY = (
    "本周整体健康状况良好，血压控制在正常范围内略偏高，建议减少钠盐摄入。"
    "\n\n本报告仅供参考，不构成医疗建议，如有不适请及时就医。"
)

FAKE_REPORT_DATA = {
    "metric_stats": json.dumps(FAKE_METRIC_STATS, ensure_ascii=False),
    "medication_stats": json.dumps(FAKE_MED_STATS, ensure_ascii=False),
    "notable_events": json.dumps(FAKE_EVENTS, ensure_ascii=False),
    "llm_summary": FAKE_SUMMARY,
    "status": "done",
}

GENERATE_PAYLOAD = {
    "period_type": "weekly",
    "period_start": "2026-04-14",
    "period_end": "2026-04-20",
}


def _mock_svc(report_data=None):
    svc = MagicMock()
    svc.generate_report = AsyncMock(return_value=report_data or FAKE_REPORT_DATA)
    return svc


def _override(svc=None):
    app.dependency_overrides[_get_service] = lambda: (svc or _mock_svc())


def _restore():
    app.dependency_overrides.pop(_get_service, None)


# ─────────────────────────────────────────────────────────────────────

class TestGenerateReport:
    """POST /{member_id}/generate"""

    async def test_generate_weekly_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常生成周报，含 LLM 总结和各项统计"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json=GENERATE_PAYLOAD,
            )
        finally:
            _restore()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["period_type"] == "weekly"
        assert data["period_start"] == "2026-04-14"
        assert data["period_end"] == "2026-04-20"
        assert data["status"] == "done"
        assert data["llm_summary"] == FAKE_SUMMARY
        assert len(data["metric_stats"]) == 1
        assert data["metric_stats"][0]["metric_type"] == "blood_pressure_sys"
        assert len(data["medication_stats"]) == 1
        assert data["medication_stats"][0]["adherence_rate"] == pytest.approx(0.857)
        assert len(data["notable_events"]) == 1
        assert data["id"] is not None

    async def test_generate_monthly_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常生成月报"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json={
                    "period_type": "monthly",
                    "period_start": "2026-04-01",
                    "period_end": "2026-04-30",
                },
            )
        finally:
            _restore()

        assert resp.status_code == 201
        assert resp.json()["period_type"] == "monthly"

    async def test_generate_no_data(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """周期内无健康记录，报告仍能生成（空统计）"""
        member_id = registered_family["member_id"]
        empty_data = {
            "metric_stats": json.dumps([]),
            "medication_stats": json.dumps([]),
            "notable_events": json.dumps([]),
            "llm_summary": "本周期暂无健康数据记录。",
            "status": "done",
        }
        _override(_mock_svc(empty_data))
        try:
            resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json={
                    "period_type": "weekly",
                    "period_start": "2025-01-01",
                    "period_end": "2025-01-07",
                },
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["metric_stats"] == []
        assert data["status"] == "done"

    async def test_llm_failure_still_saves(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 生成失败时，报告依然保存（llm_summary=None，status=done）"""
        member_id = registered_family["member_id"]
        degraded_data = {
            "metric_stats": json.dumps(FAKE_METRIC_STATS, ensure_ascii=False),
            "medication_stats": json.dumps([], ensure_ascii=False),
            "notable_events": json.dumps([], ensure_ascii=False),
            "llm_summary": None,
            "status": "done",
        }
        _override(_mock_svc(degraded_data))
        try:
            resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json={
                    "period_type": "weekly",
                    "period_start": "2026-04-07",
                    "period_end": "2026-04-13",
                },
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["llm_summary"] is None
        assert data["status"] == "done"
        assert data["metric_stats"] is not None

    async def test_generate_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        """未认证返回 401/403"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/reports/{member_id}/generate",
            json=GENERATE_PAYLOAD,
        )
        assert resp.status_code in (401, 403)

    async def test_generate_invalid_date_order(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """period_end < period_start 返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/reports/{member_id}/generate",
            headers=auth_headers,
            json={
                "period_type": "weekly",
                "period_start": "2026-04-20",
                "period_end": "2026-04-14",   # 早于 start
            },
        )
        assert resp.status_code == 422


class TestListReports:
    """GET /{member_id}"""

    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """新成员报告列表为空"""
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/reports/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_after_generate(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """生成报告后列表返回该报告"""
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json=GENERATE_PAYLOAD,
            )
        finally:
            _restore()

        resp = await client.get(f"/api/v1/reports/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        first = items[0]
        assert first["period_type"] == "weekly"
        assert "has_llm_summary" in first

    async def test_filter_by_period_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """按 period_type 过滤有效"""
        member_id = registered_family["member_id"]
        _override()
        try:
            # 生成一份周报
            await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json=GENERATE_PAYLOAD,
            )
        finally:
            _restore()

        # 查询月报，应返回空（或不包含刚才的周报）
        resp = await client.get(
            f"/api/v1/reports/{member_id}",
            headers=auth_headers,
            params={"period_type": "monthly"},
        )
        assert resp.status_code == 200
        monthly_items = resp.json()
        for item in monthly_items:
            assert item["period_type"] == "monthly"


class TestGetReport:
    """GET /{member_id}/{report_id}"""

    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """获取报告详情包含完整统计"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json=GENERATE_PAYLOAD,
            )
        finally:
            _restore()

        report_id = create_resp.json()["id"]
        resp = await client.get(
            f"/api/v1/reports/{member_id}/{report_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == report_id
        assert data["metric_stats"] is not None
        assert data["llm_summary"] == FAKE_SUMMARY

    async def test_get_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """不存在的 report_id 返回 404"""
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/reports/{member_id}/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestDeleteReport:
    """DELETE /{member_id}/{report_id}"""

    async def test_delete_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """删除报告后再查询返回 404"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/reports/{member_id}/generate",
                headers=auth_headers,
                json={
                    "period_type": "weekly",
                    "period_start": "2026-03-01",
                    "period_end": "2026-03-07",
                },
            )
        finally:
            _restore()

        report_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/api/v1/reports/{member_id}/{report_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"/api/v1/reports/{member_id}/{report_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 404

    async def test_delete_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """删除不存在报告返回 404"""
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/reports/{member_id}/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ── 服务单元测试 ──────────────────────────────────────────────────────

class TestReportService:
    """ReportService 纯逻辑单元测试（不依赖外部 IO）"""

    def _make_record(self, metric_type: str, value: float, offset_days: int = 0):
        """构造 SimpleNamespace 模拟 HealthRecord"""
        from datetime import timedelta
        return SimpleNamespace(
            metric_type=metric_type,
            value=value,
            unit="mmHg",
            measured_at=datetime(2026, 4, 14, tzinfo=timezone.utc)
            + __import__("datetime").timedelta(days=offset_days),
        )

    def test_compute_metric_stats_basic(self):
        """正确计算 avg/min/max/count"""
        svc = ReportService()
        records = [
            self._make_record("blood_pressure_sys", 120.0, 0),
            self._make_record("blood_pressure_sys", 130.0, 1),
            self._make_record("blood_pressure_sys", 125.0, 2),
            self._make_record("heart_rate", 72.0, 0),
        ]
        stats = svc.compute_metric_stats(records)
        stats_by_type = {s["metric_type"]: s for s in stats}

        assert stats_by_type["blood_pressure_sys"]["count"] == 3
        assert stats_by_type["blood_pressure_sys"]["avg"] == pytest.approx(125.0)
        assert stats_by_type["blood_pressure_sys"]["min"] == 120.0
        assert stats_by_type["blood_pressure_sys"]["max"] == 130.0
        assert stats_by_type["heart_rate"]["count"] == 1

    def test_compute_metric_stats_trend(self):
        """趋势检测：数据持续上升时应标记「上升」"""
        svc = ReportService()
        # 前半均值 100, 后半均值 130 → 上升
        records = [
            self._make_record("blood_pressure_sys", 100.0, 0),
            self._make_record("blood_pressure_sys", 100.0, 1),
            self._make_record("blood_pressure_sys", 130.0, 2),
            self._make_record("blood_pressure_sys", 130.0, 3),
        ]
        stats = svc.compute_metric_stats(records)
        assert stats[0]["trend"] == "上升"

    def test_compute_medication_stats(self):
        """依从率计算：taken / total"""
        svc = ReportService()
        med = SimpleNamespace(id=uuid.uuid4(), name="阿司匹林")
        taken_log = SimpleNamespace(medication_id=med.id, status="taken")
        missed_log = SimpleNamespace(medication_id=med.id, status="missed")
        stats = svc.compute_medication_stats([med], [taken_log, taken_log, missed_log])
        assert stats[0]["total_logs"] == 3
        assert stats[0]["taken"] == 2
        assert stats[0]["adherence_rate"] == pytest.approx(2 / 3, abs=0.001)

    def test_medication_stats_no_logs(self):
        """无依从日志时依从率为 0.0"""
        svc = ReportService()
        med = SimpleNamespace(id=uuid.uuid4(), name="二甲双胍")
        stats = svc.compute_medication_stats([med], [])
        assert stats[0]["adherence_rate"] == 0.0
        assert stats[0]["total_logs"] == 0

    def test_extract_notable_events_high(self):
        """收缩压偏高应被提取"""
        svc = ReportService()
        records = [
            self._make_record("blood_pressure_sys", 145.0),   # > 140 偏高
            self._make_record("blood_pressure_sys", 125.0),   # 正常
        ]
        events = svc.extract_notable_events(records)
        assert len(events) == 1
        assert events[0]["direction"] == "偏高"
        assert events[0]["value"] == 145.0

    def test_extract_notable_events_low(self):
        """血氧偏低应被提取"""
        svc = ReportService()
        records = [
            self._make_record("spo2", 93.0),   # < 95 偏低
        ]
        events = svc.extract_notable_events(records)
        assert len(events) == 1
        assert events[0]["direction"] == "偏低"

    def test_extract_notable_events_no_range(self):
        """无正常值域的指标（weight/height）不产生异常事件"""
        svc = ReportService()
        records = [self._make_record("weight", 999.0)]
        events = svc.extract_notable_events(records)
        assert events == []

    async def test_llm_summary_failure_returns_none(self):
        """OpenAI 调用异常时静默返回 None"""
        from unittest.mock import patch, AsyncMock

        svc = ReportService()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("network error"))
        svc._client = mock_client

        result = await svc.generate_llm_summary(
            member_nickname="张三",
            member_role="adult",
            period_type="weekly",
            period_start=date(2026, 4, 14),
            period_end=date(2026, 4, 20),
            metric_stats=[],
            medication_stats=[],
            notable_events=[],
        )
        assert result is None
