"""
安全与可观测性中间件（T024）
============================
- SecurityHeadersMiddleware  : OWASP 推荐安全响应头
- RequestIDMiddleware        : 请求唯一 ID，便于日志追踪
- ProcessTimeMiddleware      : X-Process-Time 响应耗时头
"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    注入 OWASP 推荐的安全响应头。

    防御目标：
    - X-Content-Type-Options    : 防止 MIME 嗅探（T3 - 注入）
    - X-Frame-Options           : 防止点击劫持（T5 - 安全配置）
    - X-XSS-Protection          : 旧版浏览器 XSS 过滤
    - Referrer-Policy           : 限制 Referer 泄露
    - Permissions-Policy        : 限制浏览器 API 权限
    - Content-Security-Policy   : 阻止内联脚本/外部资源注入（T3 - XSS）
    - Strict-Transport-Security : 强制 HTTPS（T2 - 加密失败，仅生产环境）
    - Cache-Control             : 防止敏感数据被缓存
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # 防 MIME 嗅探
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 防点击劫持
        response.headers["X-Frame-Options"] = "DENY"
        # 旧浏览器 XSS 过滤（现代浏览器已内置）
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # 限制 Referer 头信息泄露
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # 禁用不必要的浏览器 API
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # 严格 CSP：仅允许同源资源，防止 XSS/数据注入
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        # 防止 API 响应被缓存（含敏感数据）
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    为每个请求注入唯一 UUID，写入响应头 X-Request-ID。
    若客户端已在请求头中传入 X-Request-ID 则沿用（便于端到端追踪）。
    同时将 request_id 存入请求 state，供日志中间件/路由读取。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        # 注入到 state，方便下游读取
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ProcessTimeMiddleware(BaseHTTPMiddleware):
    """
    在响应头中写入请求处理耗时（毫秒），便于性能监控。
    X-Process-Time: 42.57 (ms)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time"] = f"{elapsed_ms:.2f}"
        return response
