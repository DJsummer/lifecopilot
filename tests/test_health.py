"""T004：健康数据录入 API 集成测试"""
import io
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


NOW_ISO = "2026-01-15T08:00:00+08:00"

pytestmark = [pytest.mark.integration, pytest.mark.health]


@pytest.mark.integration
@pytest.mark.health
class TestCreateRecord:
    """单条健康数据录入"""

    async def test_create_blood_pressure_sys(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "blood_pressure_sys", "value": 120.0, "measured_at": NOW_ISO},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["metric_type"] == "blood_pressure_sys"
        assert data["value"] == 120.0
        assert data["unit"] == "mmHg"
        assert data["source"] == "manual"

    async def test_create_heart_rate(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "heart_rate", "value": 72.0, "measured_at": NOW_ISO, "notes": "静息"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["notes"] == "静息"

    async def test_value_out_of_range_rejected(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "blood_pressure_sys", "value": 9999.0, "measured_at": NOW_ISO},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_invalid_metric_type(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "unknown_metric", "value": 1.0, "measured_at": NOW_ISO},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_no_token_forbidden(self, client: AsyncClient, registered_family: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "weight", "value": 65.0, "measured_at": NOW_ISO},
        )
        assert resp.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.health
class TestBatchCreate:
    """批量录入（JSON）"""

    async def test_batch_create_success(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records/batch",
            json={
                "records": [
                    {"metric_type": "weight", "value": 65.0, "measured_at": NOW_ISO},
                    {"metric_type": "height", "value": 172.0, "measured_at": NOW_ISO},
                    {"metric_type": "spo2", "value": 98.0, "measured_at": NOW_ISO},
                ]
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created"] == 3
        assert data["failed"] == 0

    async def test_batch_empty_rejected(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records/batch",
            json={"records": []},
            headers=auth_headers,
        )
        assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.health
class TestCsvImport:
    """CSV 批量导入"""

    async def test_import_csv_success(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        csv_content = (
            "metric_type,value,measured_at,source,notes\n"
            "blood_glucose,5.5,2026-01-01T07:00:00+08:00,import,早餐前\n"
            "blood_glucose,7.2,2026-01-01T09:00:00+08:00,import,早餐后\n"
        )
        resp = await client.post(
            f"/api/v1/health/{member_id}/records/import-csv",
            files={"file": ("health.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created"] == 2
        assert data["failed"] == 0

    async def test_import_csv_bad_value_skipped(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        csv_content = (
            "metric_type,value,measured_at,source,notes\n"
            "weight,65.0,2026-01-02T08:00:00+08:00,,\n"
            "heart_rate,9999,2026-01-02T08:00:00+08:00,,\n"  # 超出范围
        )
        resp = await client.post(
            f"/api/v1/health/{member_id}/records/import-csv",
            files={"file": ("health.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created"] == 1
        assert data["failed"] == 1

    async def test_import_non_csv_rejected(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        resp = await client.post(
            f"/api/v1/health/{member_id}/records/import-csv",
            files={"file": ("data.txt", io.BytesIO(b"col\nval"), "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.health
class TestListRecords:
    """查询健康记录列表"""

    async def _seed(self, client, member_id, auth_headers):
        """预置数据：3 条血压 + 2 条体重"""
        records = [
            {"metric_type": "blood_pressure_sys", "value": 118.0, "measured_at": "2026-01-01T08:00:00+08:00"},
            {"metric_type": "blood_pressure_sys", "value": 122.0, "measured_at": "2026-01-02T08:00:00+08:00"},
            {"metric_type": "blood_pressure_sys", "value": 125.0, "measured_at": "2026-01-03T08:00:00+08:00"},
            {"metric_type": "weight", "value": 65.0, "measured_at": "2026-01-01T08:00:00+08:00"},
            {"metric_type": "weight", "value": 64.5, "measured_at": "2026-01-08T08:00:00+08:00"},
        ]
        for r in records:
            await client.post(f"/api/v1/health/{member_id}/records", json=r, headers=auth_headers)

    async def test_list_all(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        await self._seed(client, member_id, auth_headers)
        resp = await client.get(f"/api/v1/health/{member_id}/records", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 5

    async def test_filter_by_metric_type(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        await self._seed(client, member_id, auth_headers)
        resp = await client.get(
            f"/api/v1/health/{member_id}/records",
            params={"metric_type": "weight"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["metric_type"] == "weight" for r in data["items"])

    async def test_pagination(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        await self._seed(client, member_id, auth_headers)
        resp = await client.get(
            f"/api/v1/health/{member_id}/records",
            params={"limit": 2, "offset": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) <= 2


@pytest.mark.integration
@pytest.mark.health
class TestDeleteRecord:
    """删除记录"""

    async def test_delete_success(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        create_resp = await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "steps", "value": 8000, "measured_at": NOW_ISO},
            headers=auth_headers,
        )
        record_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/health/{member_id}/records/{record_id}", headers=auth_headers)
        assert del_resp.status_code == 204

    async def test_delete_nonexistent(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        import uuid
        member_id = registered_family["member_id"]
        resp = await client.delete(
            f"/api/v1/health/{member_id}/records/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.health
class TestHealthSummary:
    """统计摘要"""

    async def test_summary_returns_stats(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        member_id = registered_family["member_id"]
        # 录入数据（使用当前时间，确保在统计窗口内）
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await client.post(
            f"/api/v1/health/{member_id}/records",
            json={"metric_type": "heart_rate", "value": 75.0, "measured_at": now},
            headers=auth_headers,
        )
        resp = await client.get(f"/api/v1/health/{member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_id"] == member_id
        assert len(data["stats"]) >= 1
        hr_stats = next((s for s in data["stats"] if s["metric_type"] == "heart_rate"), None)
        assert hr_stats is not None
        assert hr_stats["unit"] == "bpm"
        assert hr_stats["count"] >= 1

    async def test_summary_empty_member(self, client: AsyncClient, registered_family: dict, auth_headers: dict):
        """无数据时返回空 stats"""
        # 添加一个新成员
        add_resp = await client.post(
            "/api/v1/auth/family/members",
            json={"nickname": "新成员", "role": "adult"},
            headers=auth_headers,
        )
        assert add_resp.status_code == 201
        new_member_id = add_resp.json()["id"]
        resp = await client.get(f"/api/v1/health/{new_member_id}/summary", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["stats"] == []
