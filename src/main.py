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
from src.api.v1.routers import report as report_router
from src.api.v1.routers import visit as visit_router
from src.api.v1.routers import symptom as symptom_router
from src.api.v1.routers import mental_health as mental_health_router
from src.api.v1.routers import skin_analysis as skin_analysis_router
from src.api.v1.routers import nutrition as nutrition_router
from src.api.v1.routers import fitness as fitness_router
from src.api.v1.routers import alert as alert_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("LifePilot API 启动", env=settings.ENV, debug=settings.DEBUG)
    yield
    log.info("LifePilot API 关闭")


app = FastAPI(
    title="LifePilot — 家庭健康管理 API",
    version="1.0.0",
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
app.include_router(report_router.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(visit_router.router, prefix="/api/v1/visit", tags=["visit"])
app.include_router(symptom_router.router, prefix="/api/v1/symptoms", tags=["symptoms"])
app.include_router(mental_health_router.router, prefix="/api/v1/mental-health", tags=["mental-health"])
app.include_router(skin_analysis_router.router, prefix="/api/v1/skin", tags=["skin-analysis"])
app.include_router(nutrition_router.router, prefix="/api/v1/nutrition", tags=["nutrition"])
app.include_router(fitness_router.router, prefix="/api/v1/fitness", tags=["fitness"])
app.include_router(alert_router.router, prefix="/api/v1/alerts", tags=["alerts"])

