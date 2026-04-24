"""
集成测试：系统端点
GET /health
"""
import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestSystem:
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_health_no_auth_required(self, client: AsyncClient):
        """健康检查端点无需认证"""
        resp = await client.get("/health")
        assert resp.status_code == 200
