"""
集成测试：认证 API
覆盖路由：POST /register  POST /login  POST /refresh  GET /me
使用 SQLite in-memory DB，不依赖真实 Postgres
"""
import pytest
from httpx import AsyncClient


# ── 注册 ──────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.auth
class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "Smith 家",
            "nickname": "Dad",
            "email": "dad@smith.com",
            "password": "Pass1234",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["role"] == "admin"

    async def test_register_duplicate_email(self, client: AsyncClient):
        payload = {
            "family_name": "家庭A",
            "nickname": "用户A",
            "email": "dup@test.com",
            "password": "Pass1234",
        }
        await client.post("/api/v1/auth/register", json=payload)
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "EMAIL_EXISTS"

    async def test_register_weak_password_no_digit(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "家庭B",
            "nickname": "用户B",
            "email": "b@test.com",
            "password": "NoDigitPass",
        })
        assert resp.status_code == 422

    async def test_register_weak_password_no_letter(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "家庭C",
            "nickname": "用户C",
            "email": "c@test.com",
            "password": "12345678",
        })
        assert resp.status_code == 422

    async def test_register_short_password(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "家庭D",
            "nickname": "用户D",
            "email": "d@test.com",
            "password": "Ab1",
        })
        assert resp.status_code == 422

    async def test_register_invalid_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "family_name": "家庭E",
            "nickname": "用户E",
            "email": "not-an-email",
            "password": "Pass1234",
        })
        assert resp.status_code == 422


# ── 登录 ──────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.auth
class TestLogin:
    async def test_login_success(self, client: AsyncClient, registered_family: dict):
        resp = await client.post("/api/v1/auth/login", json={
            "email": registered_family["_email"],
            "password": registered_family["_password"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["role"] == "admin"

    async def test_login_wrong_password(self, client: AsyncClient, registered_family: dict):
        resp = await client.post("/api/v1/auth/login", json={
            "email": registered_family["_email"],
            "password": "WrongPass1",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_nonexistent_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@test.com",
            "password": "Pass1234",
        })
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={"email": "x@x.com"})
        assert resp.status_code == 422


# ── Token 刷新 ─────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.auth
class TestTokenRefresh:
    async def test_refresh_success(self, client: AsyncClient, registered_family: dict):
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": registered_family["refresh_token"]
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_refresh_with_access_token_fails(self, client: AsyncClient, registered_family: dict):
        """access token 不能用于 refresh"""
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": registered_family["access_token"]
        })
        assert resp.status_code == 401

    async def test_refresh_with_invalid_token(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })
        assert resp.status_code == 401


# ── /me ───────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.auth
class TestMe:
    async def test_me_success(self, client: AsyncClient, auth_headers: dict, registered_family: dict):
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == registered_family["_email"]
        assert data["role"] == "admin"

    async def test_me_no_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code in (401, 403)  # HTTPBearer returns 403 or 401 depending on FastAPI version

    async def test_me_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token"},
        )
        assert resp.status_code == 401
