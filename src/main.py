"""LifePilot API 入口"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.logging import setup_logging

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("LifePilot API 启动", env=settings.ENV, debug=settings.DEBUG)
    yield
    log.info("LifePilot API 关闭")


app = FastAPI(
    title="LifePilot — 家庭健康管理 API",
    version="0.1.0",
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


# 注册路由（后续各模块在此添加）
# from src.api.v1.routers import auth, members, health_records, chat
# app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
# app.include_router(members.router, prefix="/api/v1/members", tags=["members"])
