"""慢病趋势预测路由 — /api/v1/alerts (T005)"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.alert import (
    AlertAcknowledge,
    AlertList,
    AlertOut,
    ThresholdCreate,
    ThresholdList,
    ThresholdOut,
    TrendRequest,
    TrendSnapshotOut,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.health import MetricType
from src.models.health_alert import AlertStatus, HealthAlert, HealthThreshold, HealthTrendSnapshot
from src.models.member import Member
from src.services.alert_service import (
    _DEFAULT_THRESHOLDS,
    create_trend_snapshot,
    analyze_trend,
)

log = structlog.get_logger()
router = APIRouter()


def _check_family(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ══════════════════════════════════════════════════════════════════════
# 阈值管理
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/thresholds/defaults",
    summary="查看各指标的系统内置默认阈值",
)
async def get_default_thresholds(
    member_id: uuid.UUID,
    _: Member = Depends(get_current_member),
):
    _check_family(member_id, _)
    return {"defaults": _DEFAULT_THRESHOLDS}


@router.post(
    "/{member_id}/thresholds",
    response_model=ThresholdOut,
    status_code=status.HTTP_201_CREATED,
    summary="设置/更新某指标的个性化阈值",
)
async def upsert_threshold(
    member_id: uuid.UUID,
    body: ThresholdCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)

    stmt = select(HealthThreshold).where(
        HealthThreshold.member_id == member_id,
        HealthThreshold.metric_type == body.metric_type.value,
    )
    t = (await db.execute(stmt)).scalar_one_or_none()
    if t is None:
        t = HealthThreshold(member_id=member_id, metric_type=body.metric_type.value)
        db.add(t)

    t.warning_low = body.warning_low
    t.danger_low = body.danger_low
    t.warning_high = body.warning_high
    t.danger_high = body.danger_high
    t.enabled = body.enabled
    t.notes = body.notes

    await db.commit()
    await db.refresh(t)
    return t


@router.get(
    "/{member_id}/thresholds",
    response_model=ThresholdList,
    summary="获取成员已配置的个性化阈值列表",
)
async def list_thresholds(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    total = (await db.execute(
        select(func.count()).select_from(HealthThreshold).where(HealthThreshold.member_id == member_id)
    )).scalar_one()
    items = (await db.execute(
        select(HealthThreshold).where(HealthThreshold.member_id == member_id)
    )).scalars().all()
    return {"total": total, "items": list(items)}


@router.delete(
    "/{member_id}/thresholds/{metric_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除某指标的个性化阈值（恢复系统默认）",
)
async def delete_threshold(
    member_id: uuid.UUID,
    metric_type: str,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(HealthThreshold).where(
        HealthThreshold.member_id == member_id,
        HealthThreshold.metric_type == metric_type,
    )
    t = (await db.execute(stmt)).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="未找到该指标的阈值配置")
    await db.delete(t)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 告警记录
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/alerts",
    response_model=AlertList,
    summary="获取成员健康告警列表（可按严重度/状态/指标过滤）",
)
async def list_alerts(
    member_id: uuid.UUID,
    severity: Optional[str] = Query(None, description="info/warning/danger"),
    alert_status: Optional[str] = Query(None, alias="status", description="active/acknowledged/resolved"),
    metric_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    q = select(HealthAlert).where(HealthAlert.member_id == member_id)
    if severity:
        q = q.where(HealthAlert.severity == severity)
    if alert_status:
        q = q.where(HealthAlert.status == alert_status)
    if metric_type:
        q = q.where(HealthAlert.metric_type == metric_type)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    items = (await db.execute(
        q.order_by(HealthAlert.triggered_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "items": list(items)}


@router.get(
    "/{member_id}/alerts/{alert_id}",
    response_model=AlertOut,
    summary="获取单条告警详情",
)
async def get_alert(
    member_id: uuid.UUID,
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(HealthAlert).where(HealthAlert.id == alert_id, HealthAlert.member_id == member_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    return alert


@router.patch(
    "/{member_id}/alerts/{alert_id}/acknowledge",
    response_model=AlertOut,
    summary="确认告警（将 active → acknowledged）",
)
async def acknowledge_alert(
    member_id: uuid.UUID,
    alert_id: uuid.UUID,
    body: AlertAcknowledge = AlertAcknowledge(),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(HealthAlert).where(HealthAlert.id == alert_id, HealthAlert.member_id == member_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.status != AlertStatus.ACTIVE:
        raise HTTPException(status_code=400, detail=f"当前状态 {alert.status} 无法确认")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now(timezone.utc)
    if body.llm_advice:
        alert.llm_advice = body.llm_advice
    await db.commit()
    await db.refresh(alert)
    return alert


@router.delete(
    "/{member_id}/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除告警记录",
)
async def delete_alert(
    member_id: uuid.UUID,
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(HealthAlert).where(HealthAlert.id == alert_id, HealthAlert.member_id == member_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    await db.delete(alert)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 趋势分析
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/trends",
    response_model=TrendSnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="分析某指标趋势并保存快照（LLM 解读可选）",
)
async def create_trend(
    member_id: uuid.UUID,
    body: TrendRequest,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    snapshot = await create_trend_snapshot(
        member=member,
        metric_type=body.metric_type.value,
        db=db,
        n_records=body.n_records,
        with_llm=body.with_llm,
    )
    return snapshot


@router.get(
    "/{member_id}/trends",
    summary="获取成员已保存的趋势快照列表",
)
async def list_trends(
    member_id: uuid.UUID,
    metric_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    q = select(HealthTrendSnapshot).where(HealthTrendSnapshot.member_id == member_id)
    if metric_type:
        q = q.where(HealthTrendSnapshot.metric_type == metric_type)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    items = (await db.execute(
        q.order_by(HealthTrendSnapshot.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "items": [TrendSnapshotOut.model_validate(s) for s in items]}


@router.get(
    "/{member_id}/trends/latest",
    response_model=TrendSnapshotOut,
    summary="获取某指标最新趋势快照（不生成新的）",
)
async def get_latest_trend(
    member_id: uuid.UUID,
    metric_type: str = Query(..., description="指标类型"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = (
        select(HealthTrendSnapshot)
        .where(HealthTrendSnapshot.member_id == member_id, HealthTrendSnapshot.metric_type == metric_type)
        .order_by(HealthTrendSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="暂无该指标的趋势快照，请先调用 POST /trends 生成")
    return snapshot
