"""T016：心理健康筛查 API 集成测试"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from src.main import app
from src.api.v1.routers.mental_health import _get_service
from src.services.mental_health_service import (
    MentalHealthService,
    combine_risk,
    score_gad7,
    score_phq9,
)

pytestmark = [pytest.mark.integration, pytest.mark.mental_health]

# ── Mock NLP 分析结果 ─────────────────────────────────────────────────

FAKE_NLP_OK = {
    "mood_score": 4,
    "detected_tags": ["焦虑", "疲惫"],
    "nlp_analysis": "你的文字中透露出明显的焦虑和疲劳感，建议适当休息并与信任的人倾诉。",
    "risk_hint": "moderate",
}

FAKE_NLP_CRISIS = {
    "mood_score": 1,
    "detected_tags": ["绝望", "自我伤害"],
    "nlp_analysis": "文字中出现高风险信号，强烈建议立即联系专业心理援助。",
    "risk_hint": "crisis",
}

FAKE_NLP_DEGRADED = {
    "mood_score": None,
    "detected_tags": [],
    "nlp_analysis": None,
    "risk_hint": "low",
}

BASE_URL = "/api/v1/mental-health"


def _mock_svc(nlp=None):
    svc = MagicMock(spec=MentalHealthService)
    svc.analyze_emotion = AsyncMock(return_value=nlp or FAKE_NLP_OK)
    return svc


def _override(svc=None):
    app.dependency_overrides[_get_service] = lambda: (svc or _mock_svc())


def _restore():
    app.dependency_overrides.pop(_get_service, None)


# ── 1. 获取量表题目 ────────────────────────────────────────────────────

class TestGetQuestions:
    """量表题目接口（无需鉴权）"""

    @pytest.mark.asyncio
    async def test_get_phq9_questions(self, client: AsyncClient):
        resp = await client.get(f"{BASE_URL}/phq9/questions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["questions"]) == 9
        assert "instructions" in data
        assert data["questions"][0]["index"] == 0

    @pytest.mark.asyncio
    async def test_get_gad7_questions(self, client: AsyncClient):
        resp = await client.get(f"{BASE_URL}/gad7/questions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["questions"]) == 7
        assert "instructions" in data
        assert data["questions"][-1]["index"] == 6


# ── 2. 情绪日记 ─────────────────────────────────────────────────────

class TestCreateEmotionDiary:
    """POST /{member_id}/diary"""

    @pytest.mark.asyncio
    async def test_create_diary_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "今天压力很大，感觉喘不过气，容易发脾气"},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["entry_type"] == "diary"
            assert data["mood_score"] == FAKE_NLP_OK["mood_score"]
            assert data["nlp_analysis"] == FAKE_NLP_OK["nlp_analysis"]
            assert data["risk_level"] == "moderate"
            assert data["resources"] is not None
            assert len(data["resources"]) > 0
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_create_diary_with_tags(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={
                    "emotion_text": "很开心但有点担心未来",
                    "emotion_tags": ["担忧", "期待"],
                },
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            # emotion_tags 应包含用户提供的标签和 NLP 检测的标签
            assert "担忧" in data["emotion_tags"]
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_create_diary_crisis_risk(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """风险等级 crisis 时，资源列表应包含危机热线"""
        _override(svc=_mock_svc(nlp=FAKE_NLP_CRISIS))
        try:
            member_id = registered_family["member_id"]
            resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "我觉得活着没意义"},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["risk_level"] == "crisis"
            resources_str = " ".join(data["resources"])
            assert "120" in resources_str or "热线" in resources_str
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_create_diary_llm_failure_degrades(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 失败时静默降级，日记仍正常保存"""
        _override(svc=_mock_svc(nlp=FAKE_NLP_DEGRADED))
        try:
            member_id = registered_family["member_id"]
            resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "感觉还好，平淡的一天"},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["mood_score"] is None
            assert data["nlp_analysis"] is None
            assert data["risk_level"] == "low"   # 降级后默认 low
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_create_diary_empty_text(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "   "},
                headers=auth_headers,
            )
            assert resp.status_code == 422
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_create_diary_no_auth(
        self, client: AsyncClient, registered_family: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/diary",
            json={"emotion_text": "测试未授权"},
        )
        assert resp.status_code in (401, 403)


# ── 3. 量表评估 ─────────────────────────────────────────────────────

class TestCreateAssessment:
    """POST /{member_id}/assess"""

    PHQ9_LOW = [0] * 9        # 总分 0 → low
    PHQ9_CRISIS = [3] * 9     # 总分 27 → crisis
    GAD7_MODERATE = [1] * 7   # 总分 7 → moderate

    @pytest.mark.asyncio
    async def test_assess_phq9_low(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={"phq9_answers": self.PHQ9_LOW},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["entry_type"] == "phq9"
        assert data["phq9_score"] == 0
        assert data["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_assess_phq9_crisis(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={"phq9_answers": self.PHQ9_CRISIS},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["phq9_score"] == 27
        assert data["risk_level"] == "crisis"
        resources_str = " ".join(data["resources"])
        assert "热线" in resources_str or "120" in resources_str

    @pytest.mark.asyncio
    async def test_assess_gad7_moderate(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={"gad7_answers": self.GAD7_MODERATE},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["entry_type"] == "gad7"
        assert data["gad7_score"] == 7
        assert data["risk_level"] == "moderate"

    @pytest.mark.asyncio
    async def test_assess_combined_takes_max_risk(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """PHQ-9 low + GAD-7 moderate → 综合取 moderate"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={
                "phq9_answers": self.PHQ9_LOW,
                "gad7_answers": self.GAD7_MODERATE,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["entry_type"] == "combined"
        assert data["phq9_score"] == 0
        assert data["gad7_score"] == 7
        assert data["risk_level"] == "moderate"

    @pytest.mark.asyncio
    async def test_assess_wrong_phq9_count(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """PHQ-9 答案数量不对时返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={"phq9_answers": [1, 2, 3]},   # 只有 3 道，应为 9
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_assess_no_answers_at_all(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """不提供任何量表答案时返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE_URL}/{member_id}/assess",
            json={"emotion_text": "只写了日记，没有量表"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ── 4. 列表 ───────────────────────────────────────────────────────────

class TestListMentalHealthLogs:
    """GET /{member_id}"""

    @pytest.mark.asyncio
    async def test_list_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            # 使用全新成员（单独注册）避免前面测试产生的记录干扰
            from tests.conftest import make_register_payload
            payload = make_register_payload()
            reg = await client.post("/api/v1/auth/register", json=payload)
            mid = reg.json()["member_id"]
            token = reg.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"{BASE_URL}/{mid}", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_list_after_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "列表测试：感觉还好"},
                headers=auth_headers,
            )
            resp = await client.get(f"{BASE_URL}/{member_id}", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 1
            assert "risk_level" in data[0]
            assert "entry_type" in data[0]
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_list_filter_by_risk_level(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override(svc=_mock_svc(nlp=FAKE_NLP_CRISIS))
        try:
            member_id = registered_family["member_id"]
            await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "过滤测试：情绪极差"},
                headers=auth_headers,
            )
            resp = await client.get(
                f"{BASE_URL}/{member_id}",
                params={"risk_level": "crisis"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            for item in resp.json():
                assert item["risk_level"] == "crisis"
        finally:
            _restore()


# ── 5. 详情 & 删除 ────────────────────────────────────────────────────

class TestGetDeleteMentalHealthLog:
    """GET / DELETE /{member_id}/{log_id}"""

    @pytest.mark.asyncio
    async def test_get_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            create_resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "详情测试：今天情绪还好"},
                headers=auth_headers,
            )
            log_id = create_resp.json()["id"]
            resp = await client.get(f"{BASE_URL}/{member_id}/{log_id}", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == log_id
            assert data["entry_type"] == "diary"
            assert data["resources"] is not None
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_get_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{BASE_URL}/{member_id}/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        _override()
        try:
            member_id = registered_family["member_id"]
            create_resp = await client.post(
                f"{BASE_URL}/{member_id}/diary",
                json={"emotion_text": "删除测试记录"},
                headers=auth_headers,
            )
            log_id = create_resp.json()["id"]
            del_resp = await client.delete(
                f"{BASE_URL}/{member_id}/{log_id}", headers=auth_headers
            )
            assert del_resp.status_code == 204
            get_resp = await client.get(
                f"{BASE_URL}/{member_id}/{log_id}", headers=auth_headers
            )
            assert get_resp.status_code == 404
        finally:
            _restore()

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"{BASE_URL}/{member_id}/{fake_id}", headers=auth_headers
        )
        assert resp.status_code == 404


# ── 6. Service 单元测试 ──────────────────────────────────────────────

class TestMentalHealthService:
    """MentalHealthService 纯单元测试"""

    def test_score_phq9_boundaries(self):
        assert score_phq9([0] * 9) == (0, "low")
        assert score_phq9([1] * 9) == (9, "moderate")
        assert score_phq9([1, 1, 1, 1, 2, 1, 2, 1, 2]) == (12, "high")  # 12 → high
        assert score_phq9([3] * 9) == (27, "crisis")

    def test_score_phq9_border_values(self):
        # 5 → moderate, 10 → high, 15 → crisis
        assert score_phq9([0, 0, 0, 0, 1, 0, 0, 0, 0 + 4]) == (5, "moderate")
        assert score_phq9([1, 1, 1, 1, 1, 1, 0, 0, 3 + 1]) == (10, "high")

    def test_score_gad7_boundaries(self):
        assert score_gad7([0] * 7) == (0, "low")
        assert score_gad7([1] * 7) == (7, "moderate")
        assert score_gad7([2] * 7)[1] == "high"       # 14 → high
        assert score_gad7([3] * 7) == (21, "crisis")

    def test_combine_risk_takes_max(self):
        assert combine_risk(["low", "moderate", "high"]) == "high"
        assert combine_risk(["crisis", "low"]) == "crisis"
        assert combine_risk(["low", "low"]) == "low"
        assert combine_risk([]) == "low"

    @pytest.mark.asyncio
    async def test_analyze_emotion_success(self):
        from unittest.mock import patch, AsyncMock, MagicMock

        svc = MentalHealthService()
        fake_response = MagicMock()
        fake_response.choices[0].message.content = json.dumps({
            "mood_score": 3,
            "detected_tags": ["压力"],
            "nlp_analysis": "你似乎正在经历较大的压力。",
            "risk_hint": "moderate",
        })

        with patch.object(svc, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
            mock_get_client.return_value = mock_client

            result = await svc.analyze_emotion("我压力很大，睡不着觉")

        assert result["mood_score"] == 3
        assert "压力" in result["detected_tags"]
        assert result["risk_hint"] == "moderate"

    @pytest.mark.asyncio
    async def test_analyze_emotion_llm_failure(self):
        from unittest.mock import patch, AsyncMock, MagicMock

        svc = MentalHealthService()

        with patch.object(svc, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("LLM 连接失败")
            )
            mock_get_client.return_value = mock_client

            result = await svc.analyze_emotion("测试文本")

        assert result["mood_score"] is None
        assert result["nlp_analysis"] is None
        assert result["risk_hint"] == "low"   # 静默降级
