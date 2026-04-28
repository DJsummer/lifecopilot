"""
API 限流模块（T024）
====================
使用 slowapi（基于 limits 库）实现每端点 / 全局限流。

限流策略：
  - 全局默认       : 200 次/分钟（按 IP / 认证用户）
  - 认证端点       : 10 次/分钟（防暴力破解，T7 - 认证失败）
  - LLM 调用端点  : 30 次/分钟（控制 API 成本）
  - 视觉分析端点  : 20 次/分钟（GPT-4V 昂贵）
  - Webhook 端点  : 60 次/分钟（允许设备高频推送）

测试环境（ENV=test）：限流器使用内存存储，限额设置极高以不干扰测试。
生产/开发环境：     可通过 REDIS_URL 切换到 Redis 后端（持久化跨进程共享）。
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from src.core.config import settings


def _key_func(request: Request) -> str:
    """
    限流 Key 生成策略：
    - 已认证请求（带 Authorization 头）：使用 Bearer token 前 16 位作为 Key
      （避免同 IP 多用户相互干扰，也防止单 token 滥用）
    - 匿名请求：使用客户端 IP
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 10:
        # 用 token 前 16 位作为 key （不暴露完整 token）
        return f"token:{auth[7:23]}"
    return get_remote_address(request) or "unknown"


def _build_limiter() -> Limiter:
    """
    根据运行环境选择存储后端：
    - test 环境   : 内存后端（不依赖 Redis，且限额设置极宽松）
    - 其他环境   : 内存后端（生产推荐接入 Redis，需在此更改 storage_uri）
    """
    storage_uri = "memory://"
    # 生产环境接入 Redis（取消注释并配置 REDIS_URL）：
    # if settings.ENV == "production":
    #     storage_uri = settings.REDIS_URL
    return Limiter(key_func=_key_func, storage_uri=storage_uri)


# 全局 limiter 实例（在 main.py 加载到 app.state.limiter）
limiter = _build_limiter()


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """统一的限流错误响应，避免暴露内部实现细节。"""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "请求过于频繁，请稍后再试。",
            "retry_after": exc.retry_after if hasattr(exc, "retry_after") else None,
        },
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )


# ── 各场景限额常量（供路由装饰器复用） ───────────────────────────────

if settings.ENV == "test":
    # 测试环境：极高限额，不干扰测试
    LIMIT_AUTH       = "10000/minute"
    LIMIT_LLM        = "10000/minute"
    LIMIT_VISION     = "10000/minute"
    LIMIT_WEBHOOK    = "10000/minute"
    LIMIT_DEFAULT    = "10000/minute"
else:
    LIMIT_AUTH       = settings.RATE_LIMIT_AUTH
    LIMIT_LLM        = settings.RATE_LIMIT_LLM
    LIMIT_VISION     = settings.RATE_LIMIT_VISION
    LIMIT_WEBHOOK    = settings.RATE_LIMIT_WEBHOOK
    LIMIT_DEFAULT    = settings.RATE_LIMIT_DEFAULT
