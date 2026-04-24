"""
pytest 全局 fixtures
- 使用 SQLite in-memory 数据库（StaticPool 模式，共享单一连接）
- 每个测试使用唯一邮箱注册，避免跨测试 email 冲突（committed 数据跨测试持久化）
"""
import os
import uuid as _uuid

# 测试环境提前加载 .env.test，避免 pydantic-settings 找不到必填字段
os.environ.setdefault("ENV", "test")
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.test"), override=True)

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base, get_db
from src.main import app

# ── 内存 SQLite 引擎（测试专用）────────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    """整个测试 session 共用一个引擎，创建所有表"""
    _engine = create_async_engine(TEST_DB_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """每个测试获得独立 session"""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI 异步测试客户端，替换 get_db 为测试 session"""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def make_register_payload() -> dict:
    """生成带唯一邮箱的注册数据（避免跨测试邮箱冲突）"""
    uid = _uuid.uuid4().hex[:8]
    return {
        "family_name": f"测试家庭_{uid}",
        "nickname": "测试管理员",
        "email": f"admin_{uid}@test.com",
        "password": "Test1234",
        "gender": "male",
    }


@pytest_asyncio.fixture
async def registered_family(client: AsyncClient) -> dict:
    """已注册的家庭（唯一邮箱），返回 TokenResponse + _register_payload"""
    payload = make_register_payload()
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, f"注册失败：{resp.json()}"
    result = resp.json()
    result["_email"] = payload["email"]      # 供登录测试使用
    result["_password"] = payload["password"]
    return result


@pytest_asyncio.fixture
async def auth_headers(registered_family: dict) -> dict:
    """admin 认证请求头"""
    return {"Authorization": f"Bearer {registered_family['access_token']}"}
