"""T020：用药管理与提醒 API 集成测试"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.medication import _get_service

pytestmark = [pytest.mark.integration, pytest.mark.medication]

# ── mock 数据 ─────────────────────────────────────────────────────────

FAKE_EXPLAIN = {
    "indication": "用于治疗高血压",
    "mechanism": "通过抑制钙离子通道舒张血管",
    "common_side_effects": ["头痛", "面部潮红", "踝部水肿"],
    "instructions": "可与食物同服，避免与葡萄柚汁同服",
    "missed_dose_advice": "若距下次服药时间较近，跳过本次即可",
    "disclaimer": "本说明仅供参考，请遵医嘱用药，不可自行增减剂量。",
}

FAKE_INTERACTION_SAFE = {
    "has_interaction": False,
    "risk_level": "none",
    "interactions": [],
    "summary": "未发现明显药物相互作用",
    "advice": "请按医嘱服药",
    "disclaimer": "本分析仅供参考，请告知医生或药师您正在服用的所有药物。",
}

FAKE_INTERACTION_RISK = {
    "has_interaction": True,
    "risk_level": "moderate",
    "interactions": [
        {
            "drug_a": "华法林",
            "drug_b": "阿司匹林",
            "mechanism": "双重抗凝，增加出血风险",
            "consequence": "出血风险增加",
            "severity": "moderate",
            "management": "密切监测 INR，调整剂量",
        }
    ],
    "summary": "发现中度相互作用，需注意出血风险",
    "advice": "请告知医生您同时服用以上药物",
    "disclaimer": "本分析仅供参考，请告知医生或药师您正在服用的所有药物。",
}


def _mock_svc(explain=None, interaction=None):
    svc = MagicMock()
    svc.explain_medication = AsyncMock(return_value=explain or FAKE_EXPLAIN)
    svc.format_description = MagicMock(return_value="【适应症】用于治疗高血压\n\n本说明仅供参考。")
    svc.check_interactions = AsyncMock(return_value=interaction or FAKE_INTERACTION_SAFE)
    return svc


def _override(svc=None):
    app.dependency_overrides[_get_service] = lambda: (svc or _mock_svc())


def _restore():
    app.dependency_overrides.pop(_get_service, None)


# ─────────────────────────────────────────────────────────────────────

class TestCreateMedication:
    """POST /{member_id}"""

    async def test_create_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常创建用药方案，含提醒时间，LLM 说明自动填充"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={
                    "name": "苯磺酸氨氯地平",
                    "dosage": "5mg",
                    "frequency": "每日一次",
                    "start_date": "2026-01-01",
                    "reminder_times": ["08:00", "20:00"],
                },
            )
        finally:
            _restore()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "苯磺酸氨氯地平"
        assert data["status"] == "active"
        assert len(data["reminders"]) == 2
        assert data["llm_description"] is not None

    async def test_create_without_reminders(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """无提醒时间也可创建"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={
                    "name": "二甲双胍",
                    "dosage": "500mg",
                    "frequency": "每日三次",
                    "start_date": "2026-01-01",
                },
            )
        finally:
            _restore()
        assert resp.status_code == 201
        assert resp.json()["reminders"] == []

    async def test_create_invalid_reminder_format(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """提醒时间格式错误返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/medications/{member_id}",
            headers=auth_headers,
            json={
                "name": "阿司匹林",
                "dosage": "100mg",
                "frequency": "每日一次",
                "start_date": "2026-01-01",
                "reminder_times": ["8:00"],   # 格式错误
            },
        )
        assert resp.status_code == 422

    async def test_create_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        """未认证返回 401/403"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/medications/{member_id}",
            json={"name": "阿司匹林", "dosage": "100mg", "frequency": "每日一次", "start_date": "2026-01-01"},
        )
        assert resp.status_code in (401, 403)

    async def test_llm_failure_still_saves(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 调用失败时静默降级，依然保存用药方案"""
        member_id = registered_family["member_id"]
        failing_svc = _mock_svc()
        failing_svc.explain_medication = AsyncMock(side_effect=Exception("openai error"))
        _override(failing_svc)
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={
                    "name": "测试药物",
                    "dosage": "10mg",
                    "frequency": "每日一次",
                    "start_date": "2026-01-01",
                },
            )
        finally:
            _restore()
        assert resp.status_code == 201
        assert resp.json()["llm_description"] is None


class TestListMedications:
    """GET /{member_id}"""

    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/medications/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_after_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "维生素D", "dosage": "1000IU", "frequency": "每日一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()

        resp = await client.get(f"/api/v1/medications/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_list_filter_by_status(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """按 status=active 过滤"""
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "钙片", "dosage": "600mg", "frequency": "每日两次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()

        resp = await client.get(
            f"/api/v1/medications/{member_id}?status=active", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "active"


class TestGetMedication:
    """GET / PATCH / DELETE /{member_id}/{med_id}"""

    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "辛伐他汀", "dosage": "20mg", "frequency": "每晚一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()
        med_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/medications/{member_id}/{med_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == med_id

    async def test_get_nonexistent_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"/api/v1/medications/{member_id}/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_patch_status(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """修改状态为 paused"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "氯沙坦", "dosage": "50mg", "frequency": "每日一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()
        med_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/v1/medications/{member_id}/{med_id}",
            headers=auth_headers,
            json={"status": "paused"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "paused"

    async def test_delete_medication(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "临时药物", "dosage": "1mg", "frequency": "一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()
        med_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/api/v1/medications/{member_id}/{med_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/api/v1/medications/{member_id}/{med_id}", headers=auth_headers)
        assert get_resp.status_code == 404


class TestReminders:
    """POST / DELETE reminders"""

    async def test_add_and_delete_reminder(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "提醒测试药", "dosage": "5mg", "frequency": "每日一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()
        med_id = create_resp.json()["id"]

        add_resp = await client.post(
            f"/api/v1/medications/{member_id}/{med_id}/reminders",
            headers=auth_headers,
            params={"remind_time": "12:00"},
        )
        assert add_resp.status_code == 201
        rid = add_resp.json()["id"]
        assert add_resp.json()["remind_time"] == "12:00"

        del_resp = await client.delete(
            f"/api/v1/medications/{member_id}/{med_id}/reminders/{rid}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204


class TestAdherence:
    """依从性记录 & 统计"""

    async def _create_med(self, client, member_id, auth_headers):
        _override()
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}",
                headers=auth_headers,
                json={"name": "依从性测试药", "dosage": "5mg", "frequency": "每日一次", "start_date": "2026-01-01"},
            )
        finally:
            _restore()
        return resp.json()["id"]

    async def test_log_taken(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        med_id = await self._create_med(client, member_id, auth_headers)

        resp = await client.post(
            f"/api/v1/medications/{member_id}/{med_id}/adherence",
            headers=auth_headers,
            json={
                "scheduled_at": "2026-01-15T08:00:00+00:00",
                "actual_at": "2026-01-15T08:05:00+00:00",
                "status": "taken",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "taken"

    async def test_log_missed(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        med_id = await self._create_med(client, member_id, auth_headers)

        resp = await client.post(
            f"/api/v1/medications/{member_id}/{med_id}/adherence",
            headers=auth_headers,
            json={"scheduled_at": "2026-01-16T08:00:00+00:00", "status": "missed"},
        )
        assert resp.status_code == 201

    async def test_adherence_stats(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """记录 2 次 taken、1 次 missed 后统计正确"""
        member_id = registered_family["member_id"]
        med_id = await self._create_med(client, member_id, auth_headers)

        for day, st in [("17", "taken"), ("18", "taken"), ("19", "missed")]:
            await client.post(
                f"/api/v1/medications/{member_id}/{med_id}/adherence",
                headers=auth_headers,
                json={"scheduled_at": f"2026-01-{day}T08:00:00+00:00", "status": st},
            )

        stats_resp = await client.get(
            f"/api/v1/medications/{member_id}/{med_id}/adherence/stats", headers=auth_headers
        )
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_logs"] == 3
        assert stats["taken"] == 2
        assert stats["missed"] == 1
        assert abs(stats["adherence_rate"] - 2 / 3) < 0.01

    async def test_invalid_status_422(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        med_id = await self._create_med(client, member_id, auth_headers)
        resp = await client.post(
            f"/api/v1/medications/{member_id}/{med_id}/adherence",
            headers=auth_headers,
            json={"scheduled_at": "2026-01-20T08:00:00+00:00", "status": "invalid_status"},
        )
        assert resp.status_code == 422


class TestInteractionCheck:
    """药物相互作用检查"""

    async def test_no_interaction(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override(_mock_svc(interaction=FAKE_INTERACTION_SAFE))
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}/interaction-check",
                headers=auth_headers,
                json={"medication_names": ["氨氯地平", "美托洛尔"]},
            )
        finally:
            _restore()
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_interaction"] is False
        assert data["risk_level"] == "none"
        assert "disclaimer" in data

    async def test_with_interaction(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        _override(_mock_svc(interaction=FAKE_INTERACTION_RISK))
        try:
            resp = await client.post(
                f"/api/v1/medications/{member_id}/interaction-check",
                headers=auth_headers,
                json={"medication_names": ["华法林", "阿司匹林"]},
            )
        finally:
            _restore()
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_interaction"] is True
        assert data["risk_level"] == "moderate"
        assert len(data["interactions"]) >= 1

    async def test_requires_at_least_two_drugs(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """少于 2 种药应返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/medications/{member_id}/interaction-check",
            headers=auth_headers,
            json={"medication_names": ["阿司匹林"]},
        )
        assert resp.status_code == 422


class TestMedicationService:
    """MedicationService 单元测试"""

    async def test_explain_returns_valid_structure(self):
        from src.services.medication_service import MedicationService

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps(FAKE_EXPLAIN)
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        svc = MedicationService(openai_client=mock_client)
        result = await svc.explain_medication("苯磺酸氨氯地平", "5mg")
        assert result["indication"] == "用于治疗高血压"
        assert "disclaimer" in result

    async def test_explain_invalid_json_fallback(self):
        from src.services.medication_service import MedicationService

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "不是JSON"
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        svc = MedicationService(openai_client=mock_client)
        result = await svc.explain_medication("某药", "10mg")
        assert isinstance(result, dict)
        assert "disclaimer" in result

    async def test_check_interactions_valid(self):
        from src.services.medication_service import MedicationService

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps(FAKE_INTERACTION_RISK)
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        svc = MedicationService(openai_client=mock_client)
        result = await svc.check_interactions(["华法林", "阿司匹林"])
        assert result["has_interaction"] is True
        assert result["risk_level"] == "moderate"
