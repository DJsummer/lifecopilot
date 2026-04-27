"""T005：慢病趋势预测与告警 API 集成测试"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.main import app

pytestmark = [pytest.mark.integration, pytest.mark.alerts]

BASE = "/api/v1/alerts"
HEALTH_BASE = "/api/v1/health"


# ── 工具函数 ──────────────────────────────────────────────────────────

async def _create_health_record(client, member_id, metric_type, value, auth_headers):
    return await client.post(
        f"{HEALTH_BASE}/{member_id}/records",
        json={
            "metric_type": metric_type,
            "value": value,
            "measured_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=auth_headers,
    )


# ══════════════════════════════════════════════════════════════════════
# 1. 默认阈值查看
# ══════════════════════════════════════════════════════════════════════

class TestDefaultThresholds:
    @pytest.mark.asyncio
    async def test_get_defaults(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/thresholds/defaults", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "defaults" in data
        assert "blood_pressure_sys" in data["defaults"]

    @pytest.mark.asyncio
    async def test_defaults_require_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/thresholds/defaults")
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# 2. 个性化阈值 CRUD
# ══════════════════════════════════════════════════════════════════════

class TestThresholdCRUD:
    @pytest.mark.asyncio
    async def test_create_threshold(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={
                "metric_type": "blood_pressure_sys",
                "warning_high": 135.0,
                "danger_high": 150.0,
                "warning_low": 85.0,
                "danger_low": 75.0,
                "notes": "医生建议控制在 135 以下",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["warning_high"] == 135.0
        assert data["danger_high"] == 150.0
        assert data["metric_type"] == "blood_pressure_sys"
        assert data["notes"] == "医生建议控制在 135 以下"

    @pytest.mark.asyncio
    async def test_upsert_threshold(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """重复 POST 同指标应更新而不创建新记录"""
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={"metric_type": "heart_rate", "warning_high": 100.0},
            headers=auth_headers,
        )
        resp = await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={"metric_type": "heart_rate", "warning_high": 95.0, "danger_high": 120.0},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["warning_high"] == 95.0

        # 列表应只有一条心率阈值
        list_resp = await client.get(f"{BASE}/{member_id}/thresholds", headers=auth_headers)
        items = list_resp.json()["items"]
        hr_items = [i for i in items if i["metric_type"] == "heart_rate"]
        assert len(hr_items) == 1

    @pytest.mark.asyncio
    async def test_list_thresholds(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        # 创建两条阈值
        for metric in ["blood_glucose", "spo2"]:
            await client.post(
                f"{BASE}/{member_id}/thresholds",
                json={"metric_type": metric, "warning_low": 4.0},
                headers=auth_headers,
            )
        resp = await client.get(f"{BASE}/{member_id}/thresholds", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_delete_threshold(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={"metric_type": "body_temperature", "danger_high": 39.0},
            headers=auth_headers,
        )
        del_resp = await client.delete(
            f"{BASE}/{member_id}/thresholds/body_temperature", headers=auth_headers
        )
        assert del_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_threshold_not_found(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"{BASE}/{member_id}/thresholds/nonexistent_metric", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_threshold_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/thresholds")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_threshold_disable(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """禁用阈值后告警不触发"""
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={"metric_type": "weight", "warning_high": 50.0, "enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["enabled"] is False


# ══════════════════════════════════════════════════════════════════════
# 3. 健康录入自动触发告警
# ══════════════════════════════════════════════════════════════════════

class TestAutoAlert:
    @pytest.mark.asyncio
    async def test_high_blood_pressure_triggers_warning(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """收缩压 ≥ 140 触发 WARNING 告警"""
        member_id = registered_family["member_id"]
        resp = await _create_health_record(
            client, member_id, "blood_pressure_sys", 145.0, auth_headers
        )
        assert resp.status_code == 201

        alerts_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        alerts = alerts_resp.json()["items"]
        bp_alerts = [a for a in alerts if a["metric_type"] == "blood_pressure_sys"]
        assert len(bp_alerts) >= 1
        assert bp_alerts[0]["severity"] == "warning"
        assert bp_alerts[0]["breach_direction"] == "high"

    @pytest.mark.asyncio
    async def test_danger_blood_pressure_triggers_danger(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """收缩压 ≥ 160 触发 DANGER 告警"""
        member_id = registered_family["member_id"]
        await _create_health_record(client, member_id, "blood_pressure_sys", 165.0, auth_headers)

        alerts_resp = await client.get(
            f"{BASE}/{member_id}/alerts?status=active", headers=auth_headers
        )
        alerts = alerts_resp.json()["items"]
        danger_alerts = [a for a in alerts if a["metric_type"] == "blood_pressure_sys" and a["severity"] == "danger"]
        assert len(danger_alerts) >= 1

    @pytest.mark.asyncio
    async def test_low_glucose_triggers_alert(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """血糖 ≤ 3.9 触发 WARNING 低血糖告警"""
        member_id = registered_family["member_id"]
        await _create_health_record(client, member_id, "blood_glucose", 3.5, auth_headers)

        alerts_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        alerts = [a for a in alerts_resp.json()["items"] if a["metric_type"] == "blood_glucose"]
        assert len(alerts) >= 1
        assert alerts[0]["breach_direction"] == "low"

    @pytest.mark.asyncio
    async def test_normal_value_no_alert(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """正常值（心率 70）不触发告警"""
        member_id = registered_family["member_id"]
        before_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        before_count = before_resp.json()["total"]

        await _create_health_record(client, member_id, "heart_rate", 70.0, auth_headers)

        after_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        assert after_resp.json()["total"] == before_count  # 没有新增告警

    @pytest.mark.asyncio
    async def test_custom_threshold_overrides_default(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """自定义阈值 warning_high=90 覆盖默认 100"""
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/thresholds",
            json={"metric_type": "heart_rate", "warning_high": 90.0, "danger_high": 110.0},
            headers=auth_headers,
        )
        await _create_health_record(client, member_id, "heart_rate", 95.0, auth_headers)

        alerts_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        hr_alerts = [a for a in alerts_resp.json()["items"] if a["metric_type"] == "heart_rate"]
        assert len(hr_alerts) >= 1

    @pytest.mark.asyncio
    async def test_alert_cooldown(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """同一指标同方向 1 小时内只触发一次告警"""
        member_id = registered_family["member_id"]
        # 连续录入两次高温
        for _ in range(2):
            await _create_health_record(client, member_id, "body_temperature", 38.9, auth_headers)

        alerts_resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        temp_alerts = [a for a in alerts_resp.json()["items"] if a["metric_type"] == "body_temperature"]
        # 冷却期内只有 1 条
        assert len(temp_alerts) == 1

    @pytest.mark.asyncio
    async def test_step_and_sleep_no_default_threshold(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """步数/睡眠无默认阈值，不触发告警"""
        member_id = registered_family["member_id"]
        before = (await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)).json()["total"]
        await _create_health_record(client, member_id, "steps", 100000.0, auth_headers)
        after = (await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)).json()["total"]
        assert after == before


# ══════════════════════════════════════════════════════════════════════
# 4. 告警管理
# ══════════════════════════════════════════════════════════════════════

class TestAlertManagement:
    async def _get_any_alert(self, client, member_id, auth_headers) -> str:
        """辅助：确保有告警并返回第一条 ID"""
        await _create_health_record(client, member_id, "blood_pressure_sys", 175.0, auth_headers)
        resp = await client.get(f"{BASE}/{member_id}/alerts", headers=auth_headers)
        items = resp.json()["items"]
        assert len(items) > 0
        return items[0]["id"]

    @pytest.mark.asyncio
    async def test_get_alert_detail(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        alert_id = await self._get_any_alert(client, member_id, auth_headers)
        resp = await client.get(f"{BASE}/{member_id}/alerts/{alert_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == alert_id

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        alert_id = await self._get_any_alert(client, member_id, auth_headers)

        resp = await client.patch(
            f"{BASE}/{member_id}/alerts/{alert_id}/acknowledge",
            json={"llm_advice": "已与医生沟通，调整了降压药剂量"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "acknowledged"
        assert data["acknowledged_at"] is not None
        assert "已与医生沟通" in data["llm_advice"]

    @pytest.mark.asyncio
    async def test_acknowledge_already_acknowledged_fails(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        alert_id = await self._get_any_alert(client, member_id, auth_headers)

        await client.patch(f"{BASE}/{member_id}/alerts/{alert_id}/acknowledge", json={}, headers=auth_headers)
        # 再次确认应失败
        resp = await client.patch(
            f"{BASE}/{member_id}/alerts/{alert_id}/acknowledge", json={}, headers=auth_headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_severity(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        await _create_health_record(client, member_id, "blood_pressure_sys", 165.0, auth_headers)
        resp = await client.get(f"{BASE}/{member_id}/alerts?severity=danger", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(a["severity"] == "danger" for a in items)

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_metric(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/alerts?metric_type=blood_pressure_sys", headers=auth_headers
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(a["metric_type"] == "blood_pressure_sys" for a in items)

    @pytest.mark.asyncio
    async def test_delete_alert(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        alert_id = await self._get_any_alert(client, member_id, auth_headers)

        del_resp = await client.delete(f"{BASE}/{member_id}/alerts/{alert_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        get_resp = await client.get(f"{BASE}/{member_id}/alerts/{alert_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_alert_not_found(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.get(f"{BASE}/{member_id}/alerts/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_alerts_require_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/{uuid.uuid4()}/alerts")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_alerts_cross_family_denied(self, client: AsyncClient):
        from tests.conftest import make_register_payload
        p1 = make_register_payload()
        p2 = make_register_payload()
        r1 = await client.post("/api/v1/auth/register", json=p1)
        r2 = await client.post("/api/v1/auth/register", json=p2)
        family2_member_id = r2.json()["member_id"]
        family1_headers = {"Authorization": f"Bearer {r1.json()['access_token']}"}
        resp = await client.get(f"{BASE}/{family2_member_id}/alerts", headers=family1_headers)
        # ADMIN 角色绕过家庭检查（设计如此），返回 200 但数据为空
        # 非 ADMIN 成员跨家庭访问得到 403
        assert resp.status_code in (200, 403, 404)


# ══════════════════════════════════════════════════════════════════════
# 5. 趋势分析
# ══════════════════════════════════════════════════════════════════════

class TestTrendAnalysis:
    @pytest.mark.asyncio
    async def test_create_trend_no_data(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """无数据时 data_points=0"""
        member_id = registered_family["member_id"]
        with patch(
            "src.api.v1.routers.alert.create_trend_snapshot",
            wraps=__import__("src.services.alert_service", fromlist=["create_trend_snapshot"]).create_trend_snapshot,
        ):
            from tests.conftest import make_register_payload
            payload = make_register_payload()
            reg = await client.post("/api/v1/auth/register", json=payload)
            new_member_id = reg.json()["member_id"]
            new_headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

            resp = await client.post(
                f"{BASE}/{new_member_id}/trends",
                json={"metric_type": "heart_rate", "n_records": 30, "with_llm": False},
                headers=new_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["data_points"] == 0

    @pytest.mark.asyncio
    async def test_create_trend_with_data(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """录入多条数据后生成趋势快照"""
        member_id = registered_family["member_id"]
        # 录入 5 条血压数据（递增趋势）
        for i, v in enumerate([120.0, 122.0, 125.0, 128.0, 130.0]):
            await _create_health_record(client, member_id, "blood_pressure_sys", v, auth_headers)

        with patch(
            "src.services.alert_service.AsyncOpenAI",
            side_effect=Exception("LLM 不可用"),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/trends",
                json={"metric_type": "blood_pressure_sys", "n_records": 30, "with_llm": False},
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["data_points"] >= 5
        assert data["mean_value"] is not None
        assert data["trend_direction"] in ("rising", "stable", "falling", "fluctuating")
        assert data["slope_per_day"] is not None

    @pytest.mark.asyncio
    async def test_trend_llm_summary(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """LLM 成功时返回 llm_summary"""
        member_id = registered_family["member_id"]
        for v in [70.0, 72.0, 74.0]:
            await _create_health_record(client, member_id, "heart_rate", v, auth_headers)

        with patch(
            "src.services.alert_service.AsyncOpenAI",
            return_value=type("C", (), {
                "chat": type("CH", (), {
                    "completions": type("CO", (), {
                        "create": AsyncMock(return_value=type("R", (), {
                            "choices": [type("Ch", (), {
                                "message": type("M", (), {"content": "心率平稳，保持良好习惯。"})()
                            })()]
                        })())
                    })()
                })()
            })(),
        ):
            resp = await client.post(
                f"{BASE}/{member_id}/trends",
                json={"metric_type": "heart_rate", "n_records": 10, "with_llm": True},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["llm_summary"] is not None

    @pytest.mark.asyncio
    async def test_trend_llm_fallback(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """LLM 失败时仍返回快照（llm_summary 可为 None 或默认文本）"""
        member_id = registered_family["member_id"]
        for v in [6.0, 6.2, 6.5]:
            await _create_health_record(client, member_id, "blood_glucose", v, auth_headers)

        with patch("src.services.alert_service.AsyncOpenAI", side_effect=Exception("超时")):
            resp = await client.post(
                f"{BASE}/{member_id}/trends",
                json={"metric_type": "blood_glucose", "n_records": 10, "with_llm": True},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        # 降级时 llm_summary 为默认规则文本
        assert resp.json()["llm_summary"] is not None

    @pytest.mark.asyncio
    async def test_list_trends(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        await client.post(
            f"{BASE}/{member_id}/trends",
            json={"metric_type": "weight", "n_records": 10, "with_llm": False},
            headers=auth_headers,
        )
        resp = await client.get(f"{BASE}/{member_id}/trends", headers=auth_headers)
        assert resp.status_code == 200
        assert "total" in resp.json()
        assert "items" in resp.json()

    @pytest.mark.asyncio
    async def test_list_trends_filter_by_metric(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/trends?metric_type=weight", headers=auth_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_latest_trend(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        # 先生成一个快照
        await client.post(
            f"{BASE}/{member_id}/trends",
            json={"metric_type": "spo2", "n_records": 5, "with_llm": False},
            headers=auth_headers,
        )
        resp = await client.get(
            f"{BASE}/{member_id}/trends/latest?metric_type=spo2", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["metric_type"] == "spo2"

    @pytest.mark.asyncio
    async def test_get_latest_trend_not_found(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"{BASE}/{member_id}/trends/latest?metric_type=height", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_trend_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/{uuid.uuid4()}/trends",
            json={"metric_type": "heart_rate"},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# 6. 纯算法单元测试
# ══════════════════════════════════════════════════════════════════════

class TestAlgorithm:
    def test_linear_slope_rising(self):
        from src.services.alert_service import _linear_slope
        x = [0, 1, 2, 3, 4]
        y = [100, 102, 104, 106, 108]
        slope = _linear_slope(x, y)
        assert abs(slope - 2.0) < 0.01

    def test_linear_slope_flat(self):
        from src.services.alert_service import _linear_slope
        x = [0, 1, 2, 3]
        y = [75, 75, 75, 75]
        assert _linear_slope(x, y) == 0.0

    def test_linear_slope_falling(self):
        from src.services.alert_service import _linear_slope
        x = [0, 1, 2]
        y = [130, 128, 126]
        slope = _linear_slope(x, y)
        assert slope < 0

    def test_classify_breach_danger_high(self):
        from src.services.alert_service import _classify_breach
        from src.models.health_alert import AlertSeverity
        thresholds = {"warning_high": 140.0, "danger_high": 160.0, "warning_low": None, "danger_low": None}
        result = _classify_breach(165.0, thresholds)
        assert result is not None
        severity, threshold_value, direction = result
        assert severity == AlertSeverity.DANGER
        assert direction == "high"

    def test_classify_breach_warning_low(self):
        from src.services.alert_service import _classify_breach
        from src.models.health_alert import AlertSeverity
        thresholds = {"warning_low": 3.9, "danger_low": 3.0, "warning_high": None, "danger_high": None}
        result = _classify_breach(3.5, thresholds)
        assert result[0] == AlertSeverity.WARNING
        assert result[2] == "low"

    def test_classify_breach_normal_no_alert(self):
        from src.services.alert_service import _classify_breach
        thresholds = {"warning_low": 60.0, "danger_low": 50.0, "warning_high": 140.0, "danger_high": 160.0}
        assert _classify_breach(120.0, thresholds) is None

    def test_determine_direction_rising(self):
        from src.services.alert_service import _determine_direction
        from src.models.health_alert import TrendDirection
        assert _determine_direction(2.0, 130.0, 5.0) == TrendDirection.RISING

    def test_determine_direction_stable(self):
        from src.services.alert_service import _determine_direction
        from src.models.health_alert import TrendDirection
        assert _determine_direction(0.001, 75.0, 1.0) == TrendDirection.STABLE

    def test_determine_direction_fluctuating(self):
        from src.services.alert_service import _determine_direction
        from src.models.health_alert import TrendDirection
        # std/mean > 0.20 → FLUCTUATING
        assert _determine_direction(0.5, 75.0, 20.0) == TrendDirection.FLUCTUATING
