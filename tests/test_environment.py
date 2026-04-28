"""T017：环境健康监控 API 集成测试"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.services.environment_service import (
    check_threshold,
    compute_air_quality_level,
    parse_xiaomi_payload,
    parse_home_assistant_payload,
    _rule_advice,
    _pm25_to_level,
)
from src.models.environment import AirQualityLevel, EnvMetricType, EnvironmentRecord

pytestmark = [pytest.mark.integration, pytest.mark.environment]

BASE = "/api/v1/environment"
NOW = datetime.now(timezone.utc).isoformat()


# ── 工具函数 ──────────────────────────────────────────────────────────

def _rec(metric_type: str, value: float, **kw) -> dict:
    return {
        "metric_type": metric_type,
        "value": value,
        "measured_at": NOW,
        **kw,
    }


# ══════════════════════════════════════════════════════════════════════
# 1. 手动录入 CRUD
# ══════════════════════════════════════════════════════════════════════

class TestEnvironmentRecordCRUD:
    @pytest.mark.asyncio
    async def test_create_pm25_normal(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 12.0, location="bedroom"),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["metric_type"] == "pm2_5"
        assert data["unit"] == "μg/m³"
        assert data["is_alert"] is False
        assert data["alert_level"] is None

    @pytest.mark.asyncio
    async def test_create_pm25_warning(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 50.0),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["is_alert"] is True
        assert resp.json()["alert_level"] == "warning"

    @pytest.mark.asyncio
    async def test_create_pm25_danger(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 100.0),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["alert_level"] == "danger"

    @pytest.mark.asyncio
    async def test_create_co2_warning(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("co2", 1200.0),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["is_alert"] is True

    @pytest.mark.asyncio
    async def test_create_temperature_low(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("temperature", 10.0),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["is_alert"] is True
        assert resp.json()["alert_level"] == "danger"

    @pytest.mark.asyncio
    async def test_create_unknown_metric_rejected(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("oxygen", 20.0),
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client: AsyncClient, registered_family: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("co2", 800.0),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_records(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        for mt, val in [("pm2_5", 10.0), ("co2", 600.0), ("humidity", 50.0)]:
            await client.post(
                f"{BASE}/{member_id}/records",
                json=_rec(mt, val),
                headers=auth_headers,
            )
        resp = await client.get(f"{BASE}/{member_id}/records", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 3

    @pytest.mark.asyncio
    async def test_list_filter_metric_type(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 5.0),
            headers=auth_headers,
        )
        resp = await client.get(
            f"{BASE}/{member_id}/records?metric_type=pm2_5", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["metric_type"] == "pm2_5"

    @pytest.mark.asyncio
    async def test_list_filter_is_alert(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/records?is_alert=true", headers=auth_headers
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["is_alert"] is True

    @pytest.mark.asyncio
    async def test_get_record_detail(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        create = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("humidity", 45.0),
            headers=auth_headers,
        )
        rid = create.json()["id"]
        resp = await client.get(f"{BASE}/{member_id}/records/{rid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == rid

    @pytest.mark.asyncio
    async def test_delete_record(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        create = await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("noise", 45.0),
            headers=auth_headers,
        )
        rid = create.json()["id"]
        del_resp = await client.delete(
            f"{BASE}/{member_id}/records/{rid}", headers=auth_headers
        )
        assert del_resp.status_code == 204
        get_resp = await client.get(
            f"{BASE}/{member_id}/records/{rid}", headers=auth_headers
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_create(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = [
            _rec("pm2_5", 8.0),
            _rec("co2", 700.0),
            _rec("temperature", 22.5),
            _rec("humidity", 55.0),
        ]
        resp = await client.post(
            f"{BASE}/{member_id}/records/batch",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["total"] == 4


# ══════════════════════════════════════════════════════════════════════
# 2. 综合摘要
# ══════════════════════════════════════════════════════════════════════

class TestEnvironmentSummary:
    @pytest.mark.asyncio
    async def test_summary_empty(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "air_quality_level" in data
        assert "record_count" in data
        assert isinstance(data["latest_records"], list)

    @pytest.mark.asyncio
    async def test_summary_with_data_poor(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        # PM2.5 = 100 → VERY_POOR
        await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 100.0),
            headers=auth_headers,
        )
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["air_quality_level"] in ("very_poor", "poor", "moderate")

    @pytest.mark.asyncio
    async def test_summary_alert_count(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/records",
            json=_rec("pm2_5", 80.0),  # danger
            headers=auth_headers,
        )
        resp = await client.get(f"{BASE}/{member_id}/summary", headers=auth_headers)
        assert resp.json()["alert_count"] >= 1


# ══════════════════════════════════════════════════════════════════════
# 3. LLM 建议
# ══════════════════════════════════════════════════════════════════════

class TestEnvironmentAdvice:
    @pytest.mark.asyncio
    async def test_create_advice_mocked(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.environment.generate_environment_advice",
            new_callable=AsyncMock,
            return_value="• 建议开窗通风。\n• 使用净化器。",
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/advice",
                json={"hours": 2},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "advice_text" in data
        assert "air_quality_level" in data

    @pytest.mark.asyncio
    async def test_list_advice(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/advice", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_advice_requires_auth(self, client: AsyncClient, registered_family: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(f"{BASE}/{member_id}/advice", json={"hours": 1})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# 4. Webhook 接入
# ══════════════════════════════════════════════════════════════════════

class TestWebhook:
    @pytest.mark.asyncio
    async def test_xiaomi_webhook(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = {
            "did": "lumi.sensor_ht.abc123",
            "model": "lumi.sensor_ht",
            "attrs": {"temperature": 24.5, "humidity": 58.0},
        }
        resp = await client.post(
            f"{BASE}/{member_id}/webhook/xiaomi",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total"] == 2  # temperature + humidity
        metric_types = {r["metric_type"] for r in data["items"]}
        assert "temperature" in metric_types
        assert "humidity" in metric_types

    @pytest.mark.asyncio
    async def test_xiaomi_webhook_pm25(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = {
            "did": "lumi.airmonitor.abc",
            "attrs": {"pm2_5_density": 45.0, "co2": 950.0},
        }
        resp = await client.post(
            f"{BASE}/{member_id}/webhook/xiaomi",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_ha_webhook_co2(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = {
            "entity_id": "sensor.living_room_co2",
            "state": "1050",
            "attributes": {"unit_of_measurement": "ppm", "friendly_name": "客厅CO2"},
        }
        resp = await client.post(
            f"{BASE}/{member_id}/webhook/home-assistant",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["metric_type"] == "co2"
        assert data["items"][0]["is_alert"] is True  # 1050 > 1000

    @pytest.mark.asyncio
    async def test_ha_webhook_unknown_entity(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        payload = {
            "entity_id": "sensor.unknown_sensor",
            "state": "42",
            "attributes": {},
        }
        resp = await client.post(
            f"{BASE}/{member_id}/webhook/home-assistant",
            json=payload,
            headers=auth_headers,
        )
        # 未识别的 entity_id → 返回空列表
        assert resp.status_code == 201
        assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════
# 5. 服务层单元测试
# ══════════════════════════════════════════════════════════════════════

class TestThresholdService:
    def test_pm25_normal(self):
        ok, level = check_threshold("pm2_5", 10.0)
        assert ok is False
        assert level is None

    def test_pm25_warning(self):
        ok, level = check_threshold("pm2_5", 40.0)
        assert ok is True
        assert level == "warning"

    def test_pm25_danger(self):
        ok, level = check_threshold("pm2_5", 80.0)
        assert ok is True
        assert level == "danger"

    def test_co2_ok(self):
        ok, _ = check_threshold("co2", 800.0)
        assert ok is False

    def test_co2_warning(self):
        ok, level = check_threshold("co2", 1100.0)
        assert ok is True
        assert level == "warning"

    def test_temperature_low_warning(self):
        ok, level = check_threshold("temperature", 15.0)
        assert ok is True
        assert level == "warning"

    def test_temperature_low_danger(self):
        ok, level = check_threshold("temperature", 8.0)
        assert ok is True
        assert level == "danger"

    def test_temperature_high_warning(self):
        ok, level = check_threshold("temperature", 30.0)
        assert ok is True
        assert level == "warning"

    def test_humidity_low_warning(self):
        ok, level = check_threshold("humidity", 25.0)
        assert ok is True
        assert level == "warning"

    def test_humidity_high_danger(self):
        ok, level = check_threshold("humidity", 85.0)
        assert ok is True
        assert level == "danger"

    def test_unknown_metric(self):
        ok, level = check_threshold("unknown", 999.0)
        assert ok is False

    def test_co_danger(self):
        ok, level = check_threshold("co", 40.0)
        assert ok is True
        assert level == "danger"


class TestAirQualityLevel:
    def _make_record(self, metric_type: str, value: float) -> SimpleNamespace:
        return SimpleNamespace(metric_type=metric_type, value=value)

    def test_empty_records_good(self):
        assert compute_air_quality_level([]) == AirQualityLevel.GOOD

    def test_pm25_excellent(self):
        # PM2.5 < warning(35) → _single_record_level returns GOOD
        level = compute_air_quality_level([self._make_record("pm2_5", 5.0)])
        assert level == AirQualityLevel.GOOD

    def test_pm25_moderate(self):
        level = compute_air_quality_level([self._make_record("pm2_5", 50.0)])
        assert level == AirQualityLevel.MODERATE

    def test_pm25_very_poor(self):
        level = compute_air_quality_level([self._make_record("pm2_5", 100.0)])
        assert level == AirQualityLevel.VERY_POOR

    def test_worst_level_wins(self):
        records = [
            self._make_record("pm2_5", 5.0),   # excellent
            self._make_record("co2", 2500.0),   # danger → very_poor
        ]
        level = compute_air_quality_level(records)
        assert level == AirQualityLevel.VERY_POOR

    def test_pm25_to_level_hazardous(self):
        assert _pm25_to_level(300.0) == AirQualityLevel.HAZARDOUS


class TestPayloadParsers:
    def test_xiaomi_temperature_humidity(self):
        payload = {
            "did": "lumi.abc",
            "attrs": {"temperature": 22.0, "humidity": 60.0},
        }
        results = parse_xiaomi_payload(payload)
        assert len(results) == 2
        types = {r["metric_type"] for r in results}
        assert "temperature" in types
        assert "humidity" in types

    def test_xiaomi_invalid_value_skipped(self):
        payload = {
            "did": "lumi.abc",
            "attrs": {"temperature": "not_a_number"},
        }
        results = parse_xiaomi_payload(payload)
        assert len(results) == 0

    def test_xiaomi_unknown_attr_skipped(self):
        payload = {
            "did": "lumi.abc",
            "attrs": {"light_level": 300},  # 未映射
        }
        results = parse_xiaomi_payload(payload)
        assert len(results) == 0

    def test_ha_co2_entity(self):
        payload = {
            "entity_id": "sensor.bedroom_co2",
            "state": "900",
            "attributes": {"unit_of_measurement": "ppm"},
        }
        results = parse_home_assistant_payload(payload)
        assert len(results) == 1
        assert results[0]["metric_type"] == "co2"
        assert results[0]["value"] == 900.0

    def test_ha_temperature_entity(self):
        payload = {
            "entity_id": "sensor.living_room_temperature",
            "state": "23.5",
            "attributes": {"unit_of_measurement": "°C"},
        }
        results = parse_home_assistant_payload(payload)
        assert len(results) == 1
        assert results[0]["metric_type"] == "temperature"

    def test_ha_unknown_entity(self):
        payload = {
            "entity_id": "sensor.door_lock_state",
            "state": "locked",
            "attributes": {},
        }
        results = parse_home_assistant_payload(payload)
        assert len(results) == 0


class TestRuleAdvice:
    def _make_records(self, **kw) -> list[SimpleNamespace]:
        return [SimpleNamespace(metric_type=mt, value=val) for mt, val in kw.items()]

    def test_co_warning_in_advice(self):
        records = self._make_records(co=40.0)
        text = _rule_advice(records, AirQualityLevel.POOR)
        assert "CO" in text or "一氧化碳" in text

    def test_high_pm25_in_advice(self):
        records = self._make_records(pm2_5=80.0)
        text = _rule_advice(records, AirQualityLevel.VERY_POOR)
        assert "PM2.5" in text

    def test_low_temperature_advice(self):
        records = self._make_records(temperature=8.0)
        text = _rule_advice(records, AirQualityLevel.GOOD)
        assert "温" in text or "暖" in text

    def test_good_quality_positive_tip(self):
        text = _rule_advice([], AirQualityLevel.EXCELLENT)
        assert "良好" in text or "保持" in text

    def test_disclaimer_always_appended(self):
        text = _rule_advice([], AirQualityLevel.GOOD)
        assert "免责声明" in text
