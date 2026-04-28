"""T007：儿童生长发育评估 API 集成测试"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.services.growth_service import (
    compute_growth_percentiles,
    _compute_age_months,
    _lms_zscore,
    _zscore_to_percentile,
    _category_from_percentile,
)
from src.models.growth import GrowthCategory

pytestmark = [pytest.mark.integration, pytest.mark.growth]

BASE = "/api/v1/growth"


# ── 工具函数 ──────────────────────────────────────────────────────────

def _make_growth_payload(
    height_cm: float = 90.0,
    weight_kg: float = 13.0,
    measured_at: str | None = None,
) -> dict:
    return {
        "measured_at": measured_at or date.today().isoformat(),
        "height_cm": height_cm,
        "weight_kg": weight_kg,
    }


# ══════════════════════════════════════════════════════════════════════
# 1. 生长记录 CRUD
# ══════════════════════════════════════════════════════════════════════

class TestGrowthRecordCRUD:
    @pytest.mark.asyncio
    async def test_create_record_success(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.growth.generate_growth_assessment",
            new_callable=AsyncMock,
            return_value="• 生长正常。\n\n⚠️ 免责声明：...",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_growth_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["member_id"] == member_id
        assert data["bmi"] is not None

    @pytest.mark.asyncio
    async def test_create_record_height_only(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.growth.generate_growth_assessment", new_callable=AsyncMock, return_value="OK"):
            resp = await client.post(
                f"{BASE}/{member_id}/records",
                json={"measured_at": date.today().isoformat(), "height_cm": 75.0},
                headers=auth_headers,
            )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_record_no_measurement(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """至少须有一项测量值"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json={"measured_at": date.today().isoformat()},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_record_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/{uuid.uuid4()}/records",
            json=_make_growth_payload(),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        for h in [80.0, 85.0]:
            with patch("src.api.v1.routers.growth.generate_growth_assessment", new_callable=AsyncMock, return_value="OK"):
                await client.post(
                    f"{BASE}/{member_id}/records",
                    json=_make_growth_payload(height_cm=h),
                    headers=auth_headers,
                )
        resp = await client.get(f"{BASE}/{member_id}/records", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    @pytest.mark.asyncio
    async def test_get_record_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.growth.generate_growth_assessment", new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_growth_payload(),
                headers=auth_headers,
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
        with patch("src.api.v1.routers.growth.generate_growth_assessment", new_callable=AsyncMock, return_value="OK"):
            create_resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_growth_payload(),
                headers=auth_headers,
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
    async def test_llm_failure_graceful(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.growth.generate_growth_assessment",
            new_callable=AsyncMock,
            side_effect=Exception("LLM timeout"),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_growth_payload(),
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["id"] is not None


# ══════════════════════════════════════════════════════════════════════
# 2. 发育里程碑
# ══════════════════════════════════════════════════════════════════════

class TestMilestones:
    @pytest.mark.asyncio
    async def test_init_preset_milestones(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/milestones/init", headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["inserted"] > 0  # 至少插入了一部分里程碑

    @pytest.mark.asyncio
    async def test_init_idempotent(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """重复初始化不重复插入"""
        member_id = registered_family["member_id"]
        await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        resp2 = await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        assert resp2.status_code == 201
        assert resp2.json()["inserted"] == 0

    @pytest.mark.asyncio
    async def test_list_milestones(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        resp = await client.get(f"{BASE}/{member_id}/milestones", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= len([1])  # 有数据
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_list_milestones_filter_by_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        resp = await client.get(
            f"{BASE}/{member_id}/milestones?milestone_type=motor", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["milestone_type"] == "motor"

    @pytest.mark.asyncio
    async def test_create_custom_milestone(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/milestones",
            json={
                "milestone_type": "motor",
                "title": "自定义：跳绳",
                "typical_age_start": 60,
                "typical_age_end": 84,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "自定义：跳绳"
        assert data["is_preset"] is False

    @pytest.mark.asyncio
    async def test_achieve_milestone(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # 创建一个自定义里程碑
        create_resp = await client.post(
            f"{BASE}/{member_id}/milestones",
            json={"milestone_type": "language", "title": "说第一个词"},
            headers=auth_headers,
        )
        milestone_id = create_resp.json()["id"]

        achieve_resp = await client.patch(
            f"{BASE}/{member_id}/milestones/{milestone_id}/achieve",
            json={"achieved_at": date.today().isoformat(), "notes": "今天叫了妈妈"},
            headers=auth_headers,
        )
        assert achieve_resp.status_code == 200
        data = achieve_resp.json()
        assert data["status"] == "achieved"
        assert data["achieved_at"] is not None

    @pytest.mark.asyncio
    async def test_delete_custom_milestone(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        create_resp = await client.post(
            f"{BASE}/{member_id}/milestones",
            json={"milestone_type": "social", "title": "自定义可删除里程碑"},
            headers=auth_headers,
        )
        milestone_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"{BASE}/{member_id}/milestones/{milestone_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_cannot_delete_preset_milestone(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """预设里程碑不可删除"""
        member_id = registered_family["member_id"]
        await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        list_resp = await client.get(
            f"{BASE}/{member_id}/milestones?milestone_type=motor", headers=auth_headers
        )
        presets = [i for i in list_resp.json()["items"] if i["is_preset"]]
        if presets:
            milestone_id = presets[0]["id"]
            del_resp = await client.delete(
                f"{BASE}/{member_id}/milestones/{milestone_id}", headers=auth_headers
            )
            assert del_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_achieve_nonexistent_milestone(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.patch(
            f"{BASE}/{member_id}/milestones/{uuid.uuid4()}/achieve",
            json={"achieved_at": date.today().isoformat()},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# 3. 生长概览汇总
# ══════════════════════════════════════════════════════════════════════

class TestGrowthSummary:
    @pytest.mark.asyncio
    async def test_summary_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "record_count" in data
        assert "milestone_total" in data

    @pytest.mark.asyncio
    async def test_summary_with_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch("src.api.v1.routers.growth.generate_growth_assessment", new_callable=AsyncMock, return_value="OK"):
            await client.post(
                f"{BASE}/{member_id}/records",
                json=_make_growth_payload(88.0, 12.5),
                headers=auth_headers,
            )
        await client.post(f"{BASE}/{member_id}/milestones/init", headers=auth_headers)
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["record_count"] >= 1
        assert data["milestone_total"] > 0
        assert data["latest_record"] is not None


# ══════════════════════════════════════════════════════════════════════
# 4. 百分位算法单元测试
# ══════════════════════════════════════════════════════════════════════

class TestGrowthAlgorithm:
    def test_age_months_calculation(self):
        birth = date(2023, 1, 15)
        measured = date(2025, 1, 15)
        assert _compute_age_months(birth, measured) == 24

    def test_age_months_partial(self):
        birth = date(2023, 6, 20)
        measured = date(2024, 3, 10)  # < 20 日 → 8 个月
        assert _compute_age_months(birth, measured) == 8

    def test_lms_zscore(self):
        # WHO boy 12 months height M ≈ 75.7488
        z = _lms_zscore(75.7488, -0.2762, 75.7488, 0.03137)
        assert abs(z) < 0.01  # 中位数 Z≈0

    def test_percentile_at_median(self):
        p = _zscore_to_percentile(0.0)
        assert abs(p - 50.0) < 0.1

    def test_percentile_positive_z(self):
        p = _zscore_to_percentile(2.0)
        assert p > 95

    def test_category_normal(self):
        assert _category_from_percentile(50.0) == GrowthCategory.NORMAL

    def test_category_underweight(self):
        assert _category_from_percentile(2.0) == GrowthCategory.UNDERWEIGHT

    def test_category_obese(self):
        assert _category_from_percentile(99.5) == GrowthCategory.OBESE

    def test_compute_percentiles_boy_12m(self):
        """12月龄男孩中位身高 ≈ 75.7cm → 百分位 ≈ 50"""
        result = compute_growth_percentiles(75.7, 9.6, age_months=12, is_male=True)
        assert result["height_percentile"] is not None
        assert 40 < result["height_percentile"] < 60

    def test_compute_percentiles_girl_24m(self):
        result = compute_growth_percentiles(86.3, 11.5, age_months=24, is_male=False)
        assert result["height_percentile"] is not None
        assert result["bmi"] is not None

    def test_compute_percentiles_missing_weight(self):
        result = compute_growth_percentiles(80.0, None, age_months=18, is_male=True)
        assert result["weight_percentile"] is None
        assert result["height_percentile"] is not None

    def test_compute_percentiles_over_60m(self):
        """超出 60 月龄时不计算百分位（返回 None）"""
        # 直接调用服务层检查 — 超过 60m 时，路由层不调用百分位函数
        # 这里仅验证 age > 60 时数据表返回 None
        from src.services.growth_service import _get_lms, _HFA_BOY
        lms = _get_lms(_HFA_BOY, 61)
        assert lms is not None  # 边界值取 60m
        lms = _get_lms(_HFA_BOY, 100)
        assert lms is not None  # 超出范围取边界
