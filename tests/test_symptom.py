"""T011：症状日记 NLP 分析 API 集成测试"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.symptom import _get_service
from src.services.symptom_service import SymptomService, _score_to_advice

pytestmark = [pytest.mark.integration, pytest.mark.symptom]

# ── mock 数据 ─────────────────────────────────────────────────────────

FAKE_SYMPTOMS = [
    {"name": "头痛", "severity": "中度", "location": "右侧颞部", "duration": "3小时", "character": "搏动性"},
    {"name": "恶心", "severity": "轻微", "location": None, "duration": "1小时", "character": None},
]

FAKE_ANALYSIS = {
    "structured_symptoms": json.dumps(FAKE_SYMPTOMS, ensure_ascii=False),
    "severity_score": 5,
    "advice_level": "monitor",
    "llm_summary": "中度头痛伴恶心，建议密切观察，若加重或持续请就医。\n\n本分析仅供参考，不构成诊断意见，如有不适请及时就医。",
}

EMERGENCY_ANALYSIS = {
    "structured_symptoms": json.dumps(
        [{"name": "胸痛", "severity": "剧烈", "location": "胸部", "duration": "20分钟", "character": "压迫性"}],
        ensure_ascii=False,
    ),
    "severity_score": 9,
    "advice_level": "emergency",
    "llm_summary": "剧烈胸痛，属于紧急危险症状，请立即拨打 120 或前往急诊。\n\n本分析仅供参考，不构成诊断意见，如有不适请及时就医。",
}

DEGRADED_ANALYSIS = {
    "structured_symptoms": None,
    "severity_score": None,
    "advice_level": None,
    "llm_summary": None,
}


def _mock_svc(analysis=None):
    svc = MagicMock()
    svc.analyze = AsyncMock(return_value=analysis or FAKE_ANALYSIS)
    return svc


def _override(svc=None):
    app.dependency_overrides[_get_service] = lambda: (svc or _mock_svc())


def _restore():
    app.dependency_overrides.pop(_get_service, None)


# ─────────────────────────────────────────────────────────────────────

class TestCreateSymptomLog:
    """POST /{member_id}"""

    async def test_create_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常记录并分析症状，返回结构化结果"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "头痛伴恶心，已持续 3 小时，右侧颞部搏动性疼痛"},
            )
        finally:
            _restore()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["raw_text"] == "头痛伴恶心，已持续 3 小时，右侧颞部搏动性疼痛"
        assert data["severity_score"] == 5
        assert data["advice_level"] == "monitor"
        assert data["llm_summary"] is not None
        assert len(data["structured_symptoms"]) == 2
        assert data["structured_symptoms"][0]["name"] == "头痛"
        assert data["id"] is not None

    async def test_create_emergency_level(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """紧急症状正确返回 emergency 等级"""
        member_id = registered_family["member_id"]
        _override(_mock_svc(EMERGENCY_ANALYSIS))
        try:
            resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "剧烈胸痛，压迫感，持续 20 分钟"},
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["advice_level"] == "emergency"
        assert data["severity_score"] == 9

    async def test_create_with_occurred_at(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """可指定 occurred_at 时间"""
        member_id = registered_family["member_id"]
        _override()
        try:
            resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={
                    "raw_text": "轻微喉咙痛",
                    "occurred_at": "2026-04-20T08:00:00+00:00",
                },
            )
        finally:
            _restore()

        assert resp.status_code == 201
        assert "2026-04-20" in resp.json()["occurred_at"]

    async def test_create_empty_text_422(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """空文本返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/symptoms/{member_id}",
            headers=auth_headers,
            json={"raw_text": "   "},
        )
        assert resp.status_code == 422

    async def test_create_requires_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        """未认证返回 401/403"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/symptoms/{member_id}",
            json={"raw_text": "头痛"},
        )
        assert resp.status_code in (401, 403)

    async def test_llm_failure_still_saves(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 失败时只保存原始文本，其余字段为 None"""
        member_id = registered_family["member_id"]
        _override(_mock_svc(DEGRADED_ANALYSIS))
        try:
            resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "肚子有点不舒服"},
            )
        finally:
            _restore()

        assert resp.status_code == 201
        data = resp.json()
        assert data["raw_text"] == "肚子有点不舒服"
        assert data["severity_score"] is None
        assert data["advice_level"] is None
        assert data["structured_symptoms"] is None


class TestListSymptomLogs:
    """GET /{member_id}"""

    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"/api/v1/symptoms/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_after_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """记录后列表包含该条目"""
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "关节酸痛"},
            )
        finally:
            _restore()

        resp = await client.get(f"/api/v1/symptoms/{member_id}", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert "has_analysis" in items[0]

    async def test_filter_by_advice_level(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """按 advice_level=monitor 过滤"""
        member_id = registered_family["member_id"]
        _override()
        try:
            await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "头痛"},
            )
        finally:
            _restore()

        # 过滤 emergency（应不包含上面的 monitor 记录）
        resp = await client.get(
            f"/api/v1/symptoms/{member_id}",
            headers=auth_headers,
            params={"advice_level": "emergency"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["advice_level"] == "emergency"


class TestGetSymptomLog:
    """GET + DELETE /{member_id}/{log_id}"""

    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """详情包含 structured_symptoms"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "发烧 38.5 度，全身酸痛两天"},
            )
        finally:
            _restore()

        log_id = create_resp.json()["id"]
        resp = await client.get(
            f"/api/v1/symptoms/{member_id}/{log_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == log_id
        assert data["structured_symptoms"] is not None

    async def test_get_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"/api/v1/symptoms/{member_id}/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_delete_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """删除后再查询返回 404"""
        member_id = registered_family["member_id"]
        _override()
        try:
            create_resp = await client.post(
                f"/api/v1/symptoms/{member_id}",
                headers=auth_headers,
                json={"raw_text": "眼睛红肿"},
            )
        finally:
            _restore()

        log_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/api/v1/symptoms/{member_id}/{log_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"/api/v1/symptoms/{member_id}/{log_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 404

    async def test_delete_404(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"/api/v1/symptoms/{member_id}/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ── 服务单元测试 ──────────────────────────────────────────────────────

class TestSymptomService:
    """SymptomService 纯逻辑单元测试"""

    def test_score_to_advice_self_care(self):
        assert _score_to_advice(1) == "self_care"
        assert _score_to_advice(3) == "self_care"

    def test_score_to_advice_monitor(self):
        assert _score_to_advice(4) == "monitor"
        assert _score_to_advice(5) == "monitor"

    def test_score_to_advice_visit_soon(self):
        assert _score_to_advice(6) == "visit_soon"
        assert _score_to_advice(7) == "visit_soon"

    def test_score_to_advice_emergency(self):
        assert _score_to_advice(8) == "emergency"
        assert _score_to_advice(10) == "emergency"

    async def test_analyze_success(self):
        """LLM 返回合法 JSON 时，正确提取所有字段"""
        svc = SymptomService()
        fake_response_content = json.dumps({
            "symptoms": [{"name": "咳嗽", "severity": "轻微", "location": None, "duration": "2天", "character": "干咳"}],
            "severity_score": 3,
            "summary": "轻微干咳，可先观察",
            "disclaimer": "本分析仅供参考，不构成诊断意见，如有不适请及时就医。",
        }, ensure_ascii=False)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=fake_response_content))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        svc._client = mock_client

        result = await svc.analyze("干咳两天，没有发烧")
        assert result["severity_score"] == 3
        assert result["advice_level"] == "self_care"
        assert "咳嗽" in result["structured_symptoms"]
        assert "轻微干咳" in result["llm_summary"]
        assert "本分析仅供参考" in result["llm_summary"]

    async def test_analyze_llm_failure_returns_none_fields(self):
        """LLM 异常时所有字段均为 None"""
        svc = SymptomService()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
        svc._client = mock_client

        result = await svc.analyze("头晕")
        assert result["structured_symptoms"] is None
        assert result["severity_score"] is None
        assert result["advice_level"] is None
        assert result["llm_summary"] is None

    async def test_analyze_invalid_score_clamped(self):
        """severity_score 不在 1-10 范围时，score 置 None，advice 也置 None"""
        svc = SymptomService()
        fake_content = json.dumps({
            "symptoms": [],
            "severity_score": 99,   # 非法值
            "summary": "测试",
            "disclaimer": "仅供参考。",
        })
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=fake_content))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        svc._client = mock_client

        result = await svc.analyze("普通症状")
        assert result["severity_score"] is None
        assert result["advice_level"] is None
