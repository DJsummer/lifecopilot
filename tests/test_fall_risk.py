"""T008：老人跌倒风险评估 API 集成测试"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.services.fall_risk_service import compute_fall_risk_score, _rule_recommendations
from src.models.fall_risk import FallRiskAssessment, FallRiskLevel

pytestmark = [pytest.mark.integration, pytest.mark.fall_risk]

BASE = "/api/v1/fall-risk"
HEALTH_BASE = "/api/v1/health"


# ── 工具函数 ──────────────────────────────────────────────────────────

def _make_assessment_payload(**overrides) -> dict:
    defaults = {
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "has_fall_history": False,
        "has_osteoporosis": False,
        "has_neurological_disease": False,
        "uses_sedatives": False,
        "has_gait_disorder": False,
        "uses_walking_aid": False,
        "has_vision_impairment": False,
        "has_weakness_or_balance_issue": False,
        "lives_alone": False,
        "frequent_nocturia": False,
        "has_urge_incontinence": False,
    }
    defaults.update(overrides)
    return defaults


def _make_high_risk_payload() -> dict:
    return _make_assessment_payload(
        has_fall_history=True,        # +3
        has_neurological_disease=True, # +3
        has_gait_disorder=True,        # +3
        lives_alone=True,              # +2
    )  # 总分 = 11 → HIGH


def _make_very_high_risk_payload() -> dict:
    return _make_assessment_payload(
        has_fall_history=True,                  # +3
        has_osteoporosis=True,                  # +2
        has_neurological_disease=True,           # +3
        uses_sedatives=True,                     # +2
        has_gait_disorder=True,                  # +3
        has_weakness_or_balance_issue=True,      # +3
    )  # 总分 = 16 → VERY_HIGH


# ══════════════════════════════════════════════════════════════════════
# 1. 评估 CRUD
# ══════════════════════════════════════════════════════════════════════

class TestFallRiskAssessmentCRUD:
    @pytest.mark.asyncio
    async def test_create_low_risk(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
            new_callable=AsyncMock,
            return_value="• 低风险，保持规律运动。",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_assessment_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["total_score"] == 0
        assert data["risk_level"] == "low"
        assert data["member_id"] == member_id

    @pytest.mark.asyncio
    async def test_create_high_risk(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
            new_callable=AsyncMock,
            return_value="• 高风险建议。",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_high_risk_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_score"] == 11
        assert data["risk_level"] == "high"

    @pytest.mark.asyncio
    async def test_create_very_high_risk(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
            new_callable=AsyncMock,
            return_value="• 极高风险。",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_very_high_risk_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["risk_level"] == "very_high"
        assert resp.json()["total_score"] == 16

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/{uuid.uuid4()}/assessments",
            json=_make_assessment_payload(),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_assessments(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        for _ in range(2):
            with patch("src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
                       new_callable=AsyncMock, return_value="OK"):
                await client.post(
                    f"{BASE}/{member_id}/assessments",
                    json=_make_assessment_payload(),
                    headers=auth_headers,
                )
        resp = await client.get(f"{BASE}/{member_id}/assessments", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_filter_by_risk_level(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/assessments?risk_level=low", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_get_latest_assessment(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
                   new_callable=AsyncMock, return_value="OK"):
            await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_assessment_payload(),
                headers=auth_headers,
            )
        resp = await client.get(f"{BASE}/{member_id}/assessments/latest", headers=auth_headers)
        assert resp.status_code == 200
        assert "risk_level" in resp.json()

    @pytest.mark.asyncio
    async def test_get_latest_no_record(
        self, client: AsyncClient, auth_headers: dict
    ):
        """全新家庭成员无历史评估时返回 404"""
        # 使用固定 uuid，无记录
        resp = await client.get(
            f"{BASE}/{uuid.uuid4()}/assessments/latest", headers=auth_headers
        )
        assert resp.status_code in (404, 403)

    @pytest.mark.asyncio
    async def test_get_assessment_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
                   new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_assessment_payload(),
                headers=auth_headers,
            )
        assessment_id = create_resp.json()["id"]
        resp = await client.get(
            f"{BASE}/{member_id}/assessments/{assessment_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == assessment_id

    @pytest.mark.asyncio
    async def test_delete_assessment(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
                   new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_assessment_payload(),
                headers=auth_headers,
            )
        assessment_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"{BASE}/{member_id}/assessments/{assessment_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204
        get_resp = await client.get(
            f"{BASE}/{member_id}/assessments/{assessment_id}", headers=auth_headers
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unavailable"),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_assessment_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["id"] is not None


# ══════════════════════════════════════════════════════════════════════
# 2. 不活动检测
# ══════════════════════════════════════════════════════════════════════

class TestInactivityDetection:
    @pytest.mark.asyncio
    async def test_check_inactivity_no_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """无健康记录时返回 null（不触发）"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/inactivity/check",
            json={"threshold_hours": 4.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() is None

    @pytest.mark.asyncio
    async def test_check_inactivity_recent_activity(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """最近有活动记录时不触发告警"""
        member_id = registered_family["member_id"]
        # 写入一条刚录的步数记录
        await client.post(
            f"{HEALTH_BASE}/{member_id}/records",
            json={
                "metric_type": "steps",
                "value": 3000,
                "measured_at": datetime.now(timezone.utc).isoformat(),
            },
            headers=auth_headers,
        )
        resp = await client.post(
            f"{BASE}/{member_id}/inactivity/check",
            json={"threshold_hours": 4.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() is None  # 刚有活动，不触发

    @pytest.mark.asyncio
    async def test_check_inactivity_invalid_threshold(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/inactivity/check",
            json={"threshold_hours": 0.5},  # < 1.0，应 422
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_inactivity_logs(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/inactivity", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert isinstance(data["items"], list)


# ══════════════════════════════════════════════════════════════════════
# 3. 综合概览
# ══════════════════════════════════════════════════════════════════════

class TestFallRiskSummary:
    @pytest.mark.asyncio
    async def test_summary_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "assessment_count" in data
        assert "inactivity_log_count" in data

    @pytest.mark.asyncio
    async def test_summary_with_assessment(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.fall_risk.generate_fall_risk_recommendations",
                   new_callable=AsyncMock, return_value="OK"):
            await client.post(
                f"{BASE}/{member_id}/assessments",
                json=_make_high_risk_payload(),
                headers=auth_headers,
            )
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["assessment_count"] >= 1
        assert data["latest_assessment"] is not None
        assert data["latest_assessment"]["risk_level"] == "high"


# ══════════════════════════════════════════════════════════════════════
# 4. 评分算法单元测试
# ══════════════════════════════════════════════════════════════════════

class TestFallRiskAlgorithm:
    def _make_assessment(self, **kwargs) -> FallRiskAssessment:
        defaults = dict(
            member_id=uuid.uuid4(),
            assessed_at=datetime.now(timezone.utc),
            has_fall_history=False,
            has_osteoporosis=False,
            has_neurological_disease=False,
            uses_sedatives=False,
            has_gait_disorder=False,
            uses_walking_aid=False,
            has_vision_impairment=False,
            has_weakness_or_balance_issue=False,
            lives_alone=False,
            frequent_nocturia=False,
            has_urge_incontinence=False,
            total_score=0,
            risk_level="low",
        )
        defaults.update(kwargs)
        a = FallRiskAssessment(**defaults)
        return a

    def test_score_zero(self):
        a = self._make_assessment()
        score, level = compute_fall_risk_score(a, None)
        assert score == 0
        assert level == FallRiskLevel.LOW.value

    def test_score_low(self):
        a = self._make_assessment(lives_alone=True)  # +2
        score, level = compute_fall_risk_score(a, None)
        assert score == 2
        assert level == FallRiskLevel.LOW.value

    def test_score_moderate(self):
        a = self._make_assessment(
            has_fall_history=True,  # +3
            lives_alone=True,       # +2
        )
        score, level = compute_fall_risk_score(a, None)
        assert score == 5
        assert level == FallRiskLevel.MODERATE.value

    def test_score_high(self):
        a = self._make_assessment(
            has_fall_history=True,         # +3
            has_neurological_disease=True,  # +3
            has_gait_disorder=True,         # +3
        )
        score, level = compute_fall_risk_score(a, None)
        assert score == 9
        assert level == FallRiskLevel.HIGH.value

    def test_score_very_high(self):
        a = self._make_assessment(
            has_fall_history=True,                 # +3
            has_osteoporosis=True,                 # +2
            has_neurological_disease=True,          # +3
            has_gait_disorder=True,                 # +3
            has_weakness_or_balance_issue=True,     # +3
        )
        score, level = compute_fall_risk_score(a, None)
        assert score == 14
        assert level == FallRiskLevel.VERY_HIGH.value

    def test_age_ge_75_adds_1(self):
        a = self._make_assessment(lives_alone=True)  # +2
        score, _ = compute_fall_risk_score(a, 75)
        assert score == 3  # 2 + 1（年龄）

    def test_age_ge_85_adds_2(self):
        a = self._make_assessment(lives_alone=True)
        score, _ = compute_fall_risk_score(a, 85)
        assert score == 4  # 2 + 2（年龄）

    def test_age_lt_75_no_addition(self):
        a = self._make_assessment(lives_alone=True)
        score, _ = compute_fall_risk_score(a, 65)
        assert score == 2

    def test_all_flags_max_score(self):
        """所有11项均 True + 年龄 85 → 最高分"""
        a = self._make_assessment(
            has_fall_history=True, has_osteoporosis=True,
            has_neurological_disease=True, uses_sedatives=True,
            has_gait_disorder=True, uses_walking_aid=True,
            has_vision_impairment=True, has_weakness_or_balance_issue=True,
            lives_alone=True, frequent_nocturia=True, has_urge_incontinence=True,
        )
        score, level = compute_fall_risk_score(a, 85)
        # 3+2+3+2+3+2+2+3+2+2+2 + 2(年龄) = 28
        assert score == 28
        assert level == FallRiskLevel.VERY_HIGH.value

    def test_rule_recommendations_very_high_contains_warning(self):
        a = self._make_assessment(
            risk_level=FallRiskLevel.VERY_HIGH.value,
            has_fall_history=True,
            lives_alone=True,
            total_score=20,
        )
        a.risk_level = FallRiskLevel.VERY_HIGH.value
        text = _rule_recommendations(a)
        assert "极高风险" in text
        assert "免责声明" in text

    def test_rule_recommendations_low_positive(self):
        a = self._make_assessment(risk_level=FallRiskLevel.LOW.value, total_score=0)
        a.risk_level = FallRiskLevel.LOW.value
        text = _rule_recommendations(a)
        assert "低" in text or "规律" in text
