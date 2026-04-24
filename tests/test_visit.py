"""T019：就医准备助手 API 集成测试"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.visit import _get_service
from src.services.visit_service import VisitService

pytestmark = [pytest.mark.integration, pytest.mark.visit]

# ── mock 数据 ─────────────────────────────────────────────────────────

FAKE_SUMMARY_ZH = (
    "【基本信息与主诉】\n张三，成人，头痛伴头晕 3 天。\n\n"
    "【症状描述】\n头痛为持续性胀痛，劳累后加重，休息后略有缓解。\n\n"
    "【健康背景】\n当前服用苯磺酸氨氯地平，血压近期均值 135/88 mmHg，偏高。\n\n"
    "【就医建议要点】\n请告知医生目前用药及血压控制情况。\n\n"
    "本摘要由 AI 辅助生成，仅供就医参考，不构成诊断意见，请遵医嘱。"
)
FAKE_SUMMARY_EN = (
    "**Chief Complaint**: Headache with dizziness for 3 days.\n\n"
    "**Note**: This summary is AI-assisted and for reference only."
)

FAKE_PREPARE_DATA = {
    "medications_snapshot": json.dumps(
        [{"name": "苯磺酸氨氯地平", "dosage": "5mg", "frequency": "每日一次", "instructions": None}],
        ensure_ascii=False,
    ),
    "health_snapshot": json.dumps(
        [{"metric_type": "blood_pressure_sys", "unit": "mmHg", "latest": 138.0, "avg_recent": 135.0, "count": 7}],
        ensure_ascii=False,
    ),
    "lab_snapshot": json.dumps([], ensure_ascii=False),
    "summary_zh": FAKE_SUMMARY_ZH,
    "summary_en": None,
}

BASIC_PAYLOAD = {
    "chief_complaint": "头痛伴头晕 3 天，劳累后加重",
    "symptom_duration": "3天",
    "aggravating_factors": "劳累后加重",
    "relieving_factors": "休息后略有缓解",
    "past_medical_history": "高血压病史 2 年",
    "visit_language": "zh",
}


def _mock_svc(prepare_data=None):
    svc = MagicMock()
    svc.prepare_visit = AsyncMock(return_value=prepare_data or FAKE_PREPARE_DATA)
    return svc


def _override(svc=None):
    app.dependency_overrides[_get_service] = lambda: (svc or _mock_svc())


def _restore():
    app.dependency_overrides.pop(_get_service, None)


# ─────────────────────────────────────────────────────────────────────

class TestCreateVisitSummary:
    """POST /{member_id}"""

    async def test_create_success_zh(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常生成中文就诊摘要，含所有快照数据"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json=BASIC_PAYLOAD,
            )
        finally:
            _restore()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["chief_complaint"] == BASIC_PAYLOAD["chief_complaint"]
        assert data["symptom_duration"] == "3天"
        assert data["visit_language"] == "zh"
        assert data["summary_zh"] == FAKE_SUMMARY_ZH
        assert data["summary_en"] is None
        assert len(data["medications_snapshot"]) == 1
        assert data["medications_snapshot"][0]["name"] == "苯磺酸氨氯地平"
        assert len(data["health_snapshot"]) == 1
        assert data["lab_snapshot"] == []
        assert data["id"] is not None

    async def test_create_success_both_languages(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """visit_language=both 返回中英文摘要"""
        member_id = registered_family["member_id"]
        both_data = {**FAKE_PREPARE_DATA, "summary_en": FAKE_SUMMARY_EN}
        _override(_mock_svc(both_data))
        try:
            resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json={**BASIC_PAYLOAD, "visit_language": "both"},
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["visit_language"] == "both"
        assert data["summary_zh"] is not None
        assert data["summary_en"] == FAKE_SUMMARY_EN

    async def test_create_minimal_fields(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """仅主诉必填，其余可省略"""
        member_id = registered_family["member_id"]
        minimal_data = {
            "medications_snapshot": json.dumps([]),
            "health_snapshot": json.dumps([]),
            "lab_snapshot": json.dumps([]),
            "summary_zh": "暂无数据，建议就医。",
            "summary_en": None,
        }
        _override(_mock_svc(minimal_data))
        try:
            resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json={"chief_complaint": "发烧两天"},
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["chief_complaint"] == "发烧两天"
        assert data["symptom_duration"] is None

    async def test_create_empty_complaint_422(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """主诉为空字符串返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/visit/{member_id}",
            headers=auth_headers,
            json={"chief_complaint": "   "},
        )
        assert resp.status_code == 422

    async def test_create_invalid_lookback_422(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """health_lookback_days 超出范围返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/visit/{member_id}",
            headers=auth_headers,
            json={"chief_complaint": "头痛", "health_lookback_days": 0},
        )
        assert resp.status_code == 422

    async def test_create_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        """未认证返回 401/403"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/visit/{member_id}",
            json=BASIC_PAYLOAD,
        )
        assert resp.status_code in (401, 403)

    async def test_llm_failure_still_saves(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 失败时快照数据依然保存，summary_zh=None"""
        member_id = registered_family["member_id"]
        degraded_data = {
            "medications_snapshot": json.dumps([]),
            "health_snapshot": json.dumps([]),
            "lab_snapshot": json.dumps([]),
            "summary_zh": None,
            "summary_en": None,
        }
        _override(_mock_svc(degraded_data))
        try:
            resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json=BASIC_PAYLOAD,
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["summary_zh"] is None
        assert data["id"] is not None


class TestListVisitSummaries:
    """GET /{member_id}"""

    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/visit/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_after_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """创建后列表返回该摘要"""
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json=BASIC_PAYLOAD,
            )
        finally:
            _restore()

        resp = await client.get(f"/api/v1/visit/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        first = items[0]
        assert "chief_complaint" in first
        assert "has_summary_zh" in first
        assert "has_summary_en" in first

    async def test_list_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/visit/{member_id}")
        assert resp.status_code in (401, 403)


class TestGetVisitSummary:
    """GET /{member_id}/{visit_id}"""

    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """获取详情包含完整快照与摘要"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json=BASIC_PAYLOAD,
            )
        finally:
            _restore()

        visit_id = create_resp.json()["id"]
        resp = await client.get(
            f"/api/v1/visit/{member_id}/{visit_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == visit_id
        assert data["summary_zh"] == FAKE_SUMMARY_ZH

    async def test_get_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/visit/{member_id}/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestDeleteVisitSummary:
    """DELETE /{member_id}/{visit_id}"""

    async def test_delete_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """删除后再查询返回 404"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/visit/{member_id}",
                headers=auth_headers,
                json=BASIC_PAYLOAD,
            )
        finally:
            _restore()

        visit_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/api/v1/visit/{member_id}/{visit_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"/api/v1/visit/{member_id}/{visit_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 404

    async def test_delete_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/visit/{member_id}/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ── 服务单元测试 ──────────────────────────────────────────────────────

class TestVisitService:
    """VisitService 纯逻辑单元测试"""

    def _make_med(self, name: str, dosage: str = "10mg", freq: str = "每日一次") -> SimpleNamespace:
        return SimpleNamespace(name=name, dosage=dosage, frequency=freq, instructions=None)

    def _make_record(self, metric_type: str, value: float) -> SimpleNamespace:
        from datetime import datetime, timezone
        return SimpleNamespace(
            metric_type=metric_type,
            value=value,
            measured_at=datetime.now(tz=timezone.utc),
        )

    def _make_lab(self, has_abnormal: bool = True, report_type: str = "blood_routine") -> SimpleNamespace:
        from datetime import date
        return SimpleNamespace(
            report_date=date.today(),
            report_type=report_type,
            abnormal_items='[{"name": "白细胞", "direction": "偏高"}]' if has_abnormal else None,
            has_abnormal=has_abnormal,
        )

    def test_build_medication_snapshot(self):
        svc = VisitService()
        meds = [self._make_med("阿司匹林"), self._make_med("二甲双胍", "500mg", "每日三次")]
        snap = svc.build_medication_snapshot(meds)
        assert len(snap) == 2
        assert snap[0]["name"] == "阿司匹林"
        assert snap[1]["dosage"] == "500mg"

    def test_build_medication_snapshot_empty(self):
        svc = VisitService()
        snap = svc.build_medication_snapshot([])
        assert snap == []

    def test_build_health_snapshot(self):
        svc = VisitService()
        records = [
            self._make_record("blood_pressure_sys", 120.0),
            self._make_record("blood_pressure_sys", 130.0),
            self._make_record("heart_rate", 72.0),
        ]
        snap = svc.build_health_snapshot(records)
        by_type = {s["metric_type"]: s for s in snap}
        assert by_type["blood_pressure_sys"]["count"] == 2
        assert by_type["blood_pressure_sys"]["avg_recent"] == pytest.approx(125.0)
        assert by_type["heart_rate"]["latest"] == 72.0

    def test_build_lab_snapshot(self):
        svc = VisitService()
        labs = [self._make_lab(True), self._make_lab(False), self._make_lab(True)]
        snap = svc.build_lab_snapshot(labs)
        assert len(snap) == 3
        assert snap[0]["has_abnormal"] is True

    def test_build_lab_snapshot_max_5(self):
        """超过 5 份只取最近 5 份"""
        svc = VisitService()
        labs = [self._make_lab() for _ in range(8)]
        snap = svc.build_lab_snapshot(labs)
        assert len(snap) == 5

    async def test_summary_zh_llm_failure_returns_none(self):
        """OpenAI 异常时静默返回 None"""
        svc = VisitService()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("api error"))
        svc._client = mock_client

        result = await svc.generate_summary_zh(
            member_nickname="李四",
            member_role="adult",
            chief_complaint="发烧",
            symptom_duration=None,
            aggravating_factors=None,
            relieving_factors=None,
            past_medical_history=None,
            medication_snap=[],
            health_snap=[],
            lab_snap=[],
        )
        assert result is None

    async def test_summary_en_llm_failure_returns_none(self):
        """英文摘要 OpenAI 异常时静默返回 None"""
        svc = VisitService()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("network error"))
        svc._client = mock_client

        result = await svc.generate_summary_en(
            member_nickname="Li Si",
            member_role="adult",
            chief_complaint="fever",
            symptom_duration=None,
            aggravating_factors=None,
            relieving_factors=None,
            past_medical_history=None,
            medication_snap=[],
            health_snap=[],
            lab_snap=[],
        )
        assert result is None
