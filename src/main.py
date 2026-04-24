"""LifePilot API 入口"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.logging import setup_logging
from src.api.v1.routers import auth
from src.api.v1.routers import health as health_router
from src.api.v1.routers import chat as chat_router
from src.api.v1.routers import lab_report as lab_report_router
from src.api.v1.routers import medication as medication_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("LifePilot API 启动", env=settings.ENV, debug=settings.DEBUG)
    yield
    log.info("LifePilot API 关闭")


app = FastAPI(
    title="LifePilot — 家庭健康管理 API",
    version="0.6.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "env": settings.ENV}


# ── 路由注册 ──────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(health_router.router, prefix="/api/v1/health", tags=["health"])
app.include_router(chat_router.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(lab_report_router.router, prefix="/api/v1/lab-reports", tags=["lab-reports"])
app.include_router(medication_router.router, prefix="/api/v1/medications", tags=["medications"])

