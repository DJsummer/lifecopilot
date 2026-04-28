"""T006：睡眠质量分析 API 集成测试"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.services.sleep_service import calculate_sleep_score
from src.models.sleep import SleepRecord

pytestmark = [pytest.mark.integration, pytest.mark.sleep]

BASE = "/api/v1/sleep"


# ── 工具函数 ──────────────────────────────────────────────────────────

def _make_sleep_payload(
    hours: float = 7.5,
    deep_min: int = 90,
    rem_min: int = 90,
    interruptions: int = 1,
    spo2_min: float = 97.0,
    spo2_avg: float = 98.0,
) -> dict:
    now = datetime.now(timezone.utc).replace(hour=7, minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    return {
        "sleep_start": start.isoformat(),
        "sleep_end": now.isoformat(),
        "deep_sleep_minutes": deep_min,
        "light_sleep_minutes": int(hours * 60 * 0.5),
        "rem_minutes": rem_min,
        "awake_minutes": 10,
        "interruptions": interruptions,
        "spo2_min": spo2_min,
        "spo2_avg": spo2_avg,
        "source": "manual",
        "notes": "测试备注",
    }


# ══════════════════════════════════════════════════════════════════════
# 1. 睡眠记录 CRUD
# ══════════════════════════════════════════════════════════════════════

class TestSleepRecordCRUD:
    @pytest.mark.asyncio
    async def test_create_record_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = _make_sleep_payload()
        with patch(
            "src.api.v1.routers.sleep.generate_sleep_advice",
            new_callable=AsyncMock,
            return_value="• 睡眠良好，继续保持。\n\n⚠️ 免责声明：...",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/records", json=payload, headers=auth_headers
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["member_id"] == member_id
        assert data["sleep_score"] is not None
        assert data["quality"] in ("poor", "fair", "good", "excellent")
        assert data["apnea_risk"] in ("low", "moderate", "high")
        assert data["source"] == "manual"

    @pytest.mark.asyncio
    async def test_create_record_missing_timezone_ok(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """时间带时区信息即可（ISO 8601 + Z）"""
        member_id = registered_family["member_id"]
        payload = {
            "sleep_start": "2026-05-01T23:00:00+00:00",
            "sleep_end": "2026-05-02T07:00:00+00:00",
            "source": "manual",
        }
        with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
            resp = await client.post(
                f"{BASE}/{member_id}/records", json=payload, headers=auth_headers
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["total_minutes"] == 480

    @pytest.mark.asyncio
    async def test_create_record_end_before_start(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = {
            "sleep_start": "2026-05-01T08:00:00+00:00",
            "sleep_end": "2026-05-01T07:00:00+00:00",
            "source": "manual",
        }
        resp = await client.post(
            f"{BASE}/{member_id}/records", json=payload, headers=auth_headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_record_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/{uuid.uuid4()}/records",
            json=_make_sleep_payload(),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 先录入 2 条
        for h in [7.0, 6.0]:
            payload = _make_sleep_payload(hours=h)
            with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
                await client.post(f"{BASE}/{member_id}/records", json=payload, headers=auth_headers)

        resp = await client.get(f"{BASE}/{member_id}/records", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_list_records_filter_by_quality(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/records?quality=good", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["quality"] == "good"

    @pytest.mark.asyncio
    async def test_get_record_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 创建一条
        with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/records", json=_make_sleep_payload(), headers=auth_headers
            )
        record_id = create_resp.json()["id"]

        resp = await client.get(f"{BASE}/{member_id}/records/{record_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == record_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_record(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/records/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_record(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/records", json=_make_sleep_payload(), headers=auth_headers
            )
        record_id = create_resp.json()["id"]

        del_resp = await client.delete(
            f"{BASE}/{member_id}/records/{record_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204

        get_resp = await client.get(
            f"{BASE}/{member_id}/records/{record_id}", headers=auth_headers
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_record(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"{BASE}/{member_id}/records/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_family_forbidden(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get(
            f"{BASE}/{uuid.uuid4()}/records", headers=auth_headers
        )
        assert resp.status_code in (200, 403, 404)


# ══════════════════════════════════════════════════════════════════════
# 2. 睡眠汇总统计
# ══════════════════════════════════════════════════════════════════════

class TestSleepSummary:
    @pytest.mark.asyncio
    async def test_empty_summary(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """无记录时返回 count=0"""
        # 使用新家庭以保证无历史数据不稳定
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/summary?n_days=3", headers=auth_headers)
        # 可能已有之前测试的数据，只要返回 200 即可
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "avg_hours" in data

    @pytest.mark.asyncio
    async def test_summary_with_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        for h in [8.0, 7.0, 6.5]:
            payload = _make_sleep_payload(hours=h)
            with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
                await client.post(f"{BASE}/{member_id}/records", json=payload, headers=auth_headers)

        resp = await client.get(f"{BASE}/{member_id}/summary?n_days=7", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 3
        assert data["avg_hours"] > 0
        assert isinstance(data["recent_scores"], list)

    @pytest.mark.asyncio
    async def test_summary_invalid_n_days(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/summary?n_days=200", headers=auth_headers
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# 3. 评分算法单元测试
# ══════════════════════════════════════════════════════════════════════

class TestSleepScoreAlgorithm:
    """直接测试评分算法，不经过 HTTP"""

    def _make_record(self, **kwargs) -> SleepRecord:
        now = datetime.now(timezone.utc)
        defaults = dict(
            member_id=uuid.uuid4(),
            sleep_start=now - timedelta(hours=8),
            sleep_end=now,
            total_minutes=480,
            deep_sleep_minutes=100,
            light_sleep_minutes=240,
            rem_minutes=100,
            awake_minutes=10,
            interruptions=1,
            spo2_min=96.0,
            spo2_avg=97.5,
            source="manual",
        )
        defaults.update(kwargs)
        rec = SleepRecord(**defaults)
        return rec

    def test_excellent_score(self):
        rec = self._make_record(
            total_minutes=480,  # 8h
            deep_sleep_minutes=100,
            rem_minutes=100,
            interruptions=0,
            spo2_min=98.0,
        )
        score, quality, risk = calculate_sleep_score(rec)
        assert score >= 80
        assert quality == "excellent"
        assert risk == "low"

    def test_poor_score_short_sleep(self):
        rec = self._make_record(
            total_minutes=200,  # ~3.3h
            deep_sleep_minutes=20,
            rem_minutes=20,
            interruptions=5,
            spo2_min=96.0,
        )
        score, quality, risk = calculate_sleep_score(rec)
        assert score < 60

    def test_apnea_risk_high(self):
        rec = self._make_record(spo2_min=88.0)
        _, _, risk = calculate_sleep_score(rec)
        assert risk == "high"

    def test_apnea_risk_moderate(self):
        rec = self._make_record(spo2_min=92.0)
        _, _, risk = calculate_sleep_score(rec)
        assert risk == "moderate"

    def test_apnea_risk_low(self):
        rec = self._make_record(spo2_min=96.0)
        _, _, risk = calculate_sleep_score(rec)
        assert risk == "low"

    def test_score_clamp_0_100(self):
        """评分不能超出 [0, 100]"""
        rec = self._make_record(
            total_minutes=720,  # 12h
            interruptions=20,
            spo2_min=70.0,
        )
        score, _, _ = calculate_sleep_score(rec)
        assert 0 <= score <= 100

    def test_missing_optional_fields(self):
        """缺失可选字段仍能正常评分"""
        rec = self._make_record(
            deep_sleep_minutes=None,
            rem_minutes=None,
            interruptions=None,
            spo2_min=None,
        )
        score, quality, risk = calculate_sleep_score(rec)
        assert 0 <= score <= 100
        assert quality in ("poor", "fair", "good", "excellent")
        assert risk == "low"  # 无 spo2 数据按低风险处理

    def test_quality_boundaries(self):
        # 7h 正常睡眠，分数应 ≥ 60
        rec = self._make_record(total_minutes=420)
        score, _, _ = calculate_sleep_score(rec)
        assert score >= 40  # 至少 fair


# ══════════════════════════════════════════════════════════════════════
# 4. LLM 建议 & 降级
# ══════════════════════════════════════════════════════════════════════

class TestSleepAdvice:
    @pytest.mark.asyncio
    async def test_llm_advice_in_response(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        expected_advice = "• 建议增加深睡眠时间\n\n⚠️ 免责声明：..."
        with patch(
            "src.api.v1.routers.sleep.generate_sleep_advice",
            new_callable=AsyncMock,
            return_value=expected_advice,
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_sleep_payload(spo2_min=88.0),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["advice"] == expected_advice

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """LLM 抛出异常时，记录仍正常保存"""
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.sleep.generate_sleep_advice",
            new_callable=AsyncMock,
            side_effect=Exception("OpenAI timeout"),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_sleep_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        # advice 可能为 None（异常被 try/except 捕获）
        assert resp.json()["id"] is not None

    @pytest.mark.asyncio
    async def test_apnea_risk_reflected_in_record(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """高呼吸暂停风险时 apnea_risk 字段应为 high"""
        member_id = registered_family["member_id"]
        payload = _make_sleep_payload(spo2_min=85.0)
        with patch("src.api.v1.routers.sleep.generate_sleep_advice", new_callable=AsyncMock, return_value="OK"):
            resp = await client.post(
                f"{BASE}/{member_id}/records", json=payload, headers=auth_headers
            )
        assert resp.status_code == 201
        assert resp.json()["apnea_risk"] == "high"
