"""
集成测试：家庭成员管理 API
覆盖路由：
  GET    /api/v1/auth/family
  POST   /api/v1/auth/family/members
  PATCH  /api/v1/auth/family/members/{id}
  DELETE /api/v1/auth/family/members/{id}
"""
import pytest
from httpx import AsyncClient


# ── 家庭信息 ──────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.member
class TestGetFamily:
    async def test_admin_can_get_family(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/v1/auth/family", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "invite_code" in data
        assert len(data["members"]) == 1  # 注册时创建的 admin

    async def test_no_token_forbidden(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/family")
        assert resp.status_code in (401, 403)


# ── 添加成员 ──────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.member
class TestAddMember:
    async def test_admin_add_adult_member(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={
                "nickname": "妈妈",
                "role": "adult",
                "gender": "female",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["nickname"] == "妈妈"
        assert data["role"] == "adult"

    async def test_admin_add_child_member(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"nickname": "小明", "role": "child", "birth_date": "2018-05-01"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "child"

    async def test_admin_add_elder_member(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"nickname": "爷爷", "role": "elder"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "elder"

    async def test_add_member_with_login_credential(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={
                "nickname": "妹妹",
                "role": "adult",
                "email": "sister@test.com",
                "password": "Pass1234",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "sister@test.com"

    async def test_add_member_duplicate_email(self, client: AsyncClient, auth_headers: dict):
        payload = {"nickname": "用户X", "role": "adult", "email": "dup2@test.com", "password": "Pass1234"}
        await client.post("/api/v1/auth/family/members", headers=auth_headers, json=payload)
        resp = await client.post("/api/v1/auth/family/members", headers=auth_headers, json=payload)
        assert resp.status_code == 409

    async def test_non_admin_cannot_add_member(
        self, client: AsyncClient, auth_headers: dict, registered_family: dict
    ):
        """adult 成员不能添加其他成员"""
        # 先由 admin 添加一个有登录权限的 adult
        await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"nickname": "哥哥", "role": "adult", "email": "brother@test.com", "password": "Pass1234"},
        )
        # brother 登录
        login = await client.post("/api/v1/auth/login", json={"email": "brother@test.com", "password": "Pass1234"})
        brother_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # 尝试添加成员
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=brother_headers,
            json={"nickname": "小弟", "role": "adult"},
        )
        assert resp.status_code == 403

    async def test_add_member_missing_nickname(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"role": "adult"},
        )
        assert resp.status_code == 422


# ── 更新成员 ──────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.member
class TestUpdateMember:
    async def test_admin_update_member(self, client: AsyncClient, auth_headers: dict):
        # 先添加成员
        add = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"nickname": "奶奶", "role": "elder"},
        )
        member_id = add.json()["id"]

        resp = await client.patch(
            f"/api/v1/auth/family/members/{member_id}",
            headers=auth_headers,
            json={"nickname": "奶奶（更新）", "notes": "高血压患者"},
        )
        assert resp.status_code == 200
        assert resp.json()["nickname"] == "奶奶（更新）"

    async def test_update_nonexistent_member(self, client: AsyncClient, auth_headers: dict):
        import uuid
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/auth/family/members/{fake_id}",
            headers=auth_headers,
            json={"nickname": "不存在"},
        )
        assert resp.status_code == 404

    async def test_update_self(self, client: AsyncClient, registered_family: dict):
        """成员可以更新自己的信息"""
        headers = {"Authorization": f"Bearer {registered_family['access_token']}"}
        member_id = str(registered_family["member_id"])
        resp = await client.patch(
            f"/api/v1/auth/family/members/{member_id}",
            headers=headers,
            json={"nickname": "我自己更新"},
        )
        assert resp.status_code == 200


# ── 删除成员 ──────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.member
class TestDeleteMember:
    async def test_admin_delete_member(self, client: AsyncClient, auth_headers: dict):
        add = await client.post(
            "/api/v1/auth/family/members",
            headers=auth_headers,
            json={"nickname": "待删除成员", "role": "adult"},
        )
        member_id = add.json()["id"]
        resp = await client.delete(
            f"/api/v1/auth/family/members/{member_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

    async def test_admin_cannot_delete_self(self, client: AsyncClient, auth_headers: dict, registered_family: dict):
        admin_id = str(registered_family["member_id"])
        resp = await client.delete(
            f"/api/v1/auth/family/members/{admin_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "CANNOT_DELETE_SELF"

    async def test_delete_nonexistent_member(self, client: AsyncClient, auth_headers: dict):
        import uuid
        resp = await client.delete(
            f"/api/v1/auth/family/members/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404
