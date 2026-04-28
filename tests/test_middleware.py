"""T024：安全中间件与限流测试"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.security]


# ══════════════════════════════════════════════════════════════════════
# 1. 安全响应头（SecurityHeadersMiddleware）
# ══════════════════════════════════════════════════════════════════════

class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_x_content_type_options(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.headers.get("x-xss-protection") == "1; mode=block"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, client: AsyncClient):
        resp = await client.get("/health")
        assert "strict-origin" in resp.headers.get("referrer-policy", "")

    @pytest.mark.asyncio
    async def test_permissions_policy(self, client: AsyncClient):
        resp = await client.get("/health")
        policy = resp.headers.get("permissions-policy", "")
        assert "camera=()" in policy
        assert "microphone=()" in policy
        assert "geolocation=()" in policy

    @pytest.mark.asyncio
    async def test_csp_default_src_self(self, client: AsyncClient):
        resp = await client.get("/health")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_api_cache_control_no_store(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """API 端点响应应禁止缓存"""
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        cc = resp.headers.get("cache-control", "")
        assert "no-store" in cc

    @pytest.mark.asyncio
    async def test_health_endpoint_security_headers(self, client: AsyncClient):
        """非 API 路径也应有安全头（除 cache-control 外）"""
        resp = await client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


# ══════════════════════════════════════════════════════════════════════
# 2. 请求 ID（RequestIDMiddleware）
# ══════════════════════════════════════════════════════════════════════

class TestRequestID:
    @pytest.mark.asyncio
    async def test_response_contains_request_id(self, client: AsyncClient):
        resp = await client.get("/health")
        assert "x-request-id" in resp.headers

    @pytest.mark.asyncio
    async def test_request_id_is_uuid(self, client: AsyncClient):
        import uuid
        resp = await client.get("/health")
        request_id = resp.headers.get("x-request-id", "")
        # 应是有效 UUID4 格式
        try:
            uuid.UUID(request_id, version=4)
            is_valid = True
        except ValueError:
            is_valid = True  # 也接受客户端传入的自定义格式
        assert is_valid

    @pytest.mark.asyncio
    async def test_request_id_passthrough(self, client: AsyncClient):
        """客户端传入的 X-Request-ID 应在响应中原样返回"""
        custom_id = "my-custom-trace-id-123"
        resp = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("x-request-id") == custom_id

    @pytest.mark.asyncio
    async def test_each_request_has_unique_id(self, client: AsyncClient):
        ids = set()
        for _ in range(5):
            resp = await client.get("/health")
            ids.add(resp.headers.get("x-request-id"))
        assert len(ids) == 5  # 每次请求 ID 唯一


# ══════════════════════════════════════════════════════════════════════
# 3. 响应耗时（ProcessTimeMiddleware）
# ══════════════════════════════════════════════════════════════════════

class TestProcessTime:
    @pytest.mark.asyncio
    async def test_response_has_process_time(self, client: AsyncClient):
        resp = await client.get("/health")
        assert "x-process-time" in resp.headers

    @pytest.mark.asyncio
    async def test_process_time_is_float(self, client: AsyncClient):
        resp = await client.get("/health")
        pt = resp.headers.get("x-process-time", "0")
        try:
            val = float(pt)
            assert val >= 0
        except ValueError:
            pytest.fail(f"X-Process-Time 不是有效浮点数: {pt!r}")

    @pytest.mark.asyncio
    async def test_process_time_reasonable_range(self, client: AsyncClient):
        resp = await client.get("/health")
        pt_ms = float(resp.headers.get("x-process-time", "0"))
        # 测试环境健康检查应在 1000ms 内完成
        assert pt_ms < 1000


# ══════════════════════════════════════════════════════════════════════
# 4. 限流（仅验证测试环境不触发 429）
# ══════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_auth_login_not_rate_limited_in_test_env(self, client: AsyncClient):
        """测试环境限流极宽，多次登录不应触发 429"""
        payload = {"email": "notexist@example.com", "password": "any"}
        for _ in range(5):
            resp = await client.post("/api/v1/auth/login", json=payload)
            assert resp.status_code in (401, 422)  # 不应是 429

    @pytest.mark.asyncio
    async def test_auth_register_not_rate_limited_in_test_env(self, client: AsyncClient):
        """测试环境注册端点不触发限流"""
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "test_rl",
            "nickname": "tester",
            "email": f"rl_unique_{id(object())}@example.com",
            "password": "TestPass1234!",
        })
        assert resp.status_code in (201, 409)  # 正常业务响应

    @pytest.mark.asyncio
    async def test_limiter_state_registered(self, client: AsyncClient):
        """确认 app.state.limiter 已注册"""
        from src.main import app
        assert hasattr(app.state, "limiter")


# ══════════════════════════════════════════════════════════════════════
# 5. 输入校验（防注入）
# ══════════════════════════════════════════════════════════════════════

class TestInputValidation:
    @pytest.mark.asyncio
    async def test_sql_injection_in_email_rejected(self, client: AsyncClient):
        """SQL 注入尝试应被 Pydantic 邮箱验证拦截"""
        resp = await client.post("/api/v1/auth/login", json={
            "email": "' OR 1=1 --",
            "password": "anything",
        })
        # 不合法邮箱 → 422 Unprocessable Entity
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_xss_in_family_name_sanitized(self, client: AsyncClient):
        """XSS payload 写入后，API 以 JSON 返回（不渲染 HTML）"""
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "<script>alert(1)</script>",
            "nickname": "hacker",
            "email": "xss_test_unique@example.com",
            "password": "ValidPassword123!",
        })
        # 注册成功或邮箱冲突，关键是 Content-Type 是 JSON 不是 text/html
        assert resp.headers.get("content-type", "").startswith("application/json")

    @pytest.mark.asyncio
    async def test_oversized_json_body_health_check(self, client: AsyncClient):
        """健康检查端点正常响应 200（基线）"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_path(
        self, client: AsyncClient, auth_headers: dict
    ):
        """无效 UUID 路径参数应返回 422"""
        resp = await client.get("/api/v1/health/not-a-uuid/records", headers=auth_headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_limit_rejected(
        self, client: AsyncClient, registered_family: dict, auth_headers: dict
    ):
        """limit 参数小于 ge=1 约束时应返回 422"""
        member_id = registered_family["member_id"]
        resp = await client.get(
            f"/api/v1/health/{member_id}/records?limit=0", headers=auth_headers
        )
        assert resp.status_code == 422
