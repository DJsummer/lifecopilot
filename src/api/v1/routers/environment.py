"""环境健康监控路由 — /api/v1/environment (T017)"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.environment import (
    AdviceRequest,
    EnvironmentAdviceOut,
    EnvironmentRecordCreate,
    EnvironmentRecordList,
    EnvironmentRecordOut,
    EnvironmentSummary,
    HomeAssistantWebhookPayload,
    XiaomiWebhookPayload,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.environment import EnvironmentAdvice, EnvironmentRecord
from src.models.member import Member
from src.services.environment_service import (
    check_threshold,
    compute_air_quality_level,
    generate_environment_advice,
    get_default_unit,
    parse_home_assistant_payload,
    parse_xiaomi_payload,
)

log = structlog.get_logger()
router = APIRouter()


async def _get_family_id(member_id: uuid.UUID, db: AsyncSession) -> uuid.UUID:
    from src.models.member import Member as M
    m = (await db.execute(select(M).where(M.id == member_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    return m.family_id


def _check(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _build_record(
    family_id: uuid.UUID,
    body: EnvironmentRecordCreate,
) -> EnvironmentRecord:
    unit = body.unit or get_default_unit(body.metric_type)
    is_alert, alert_level = check_threshold(body.metric_type, body.value)
    return EnvironmentRecord(
        family_id=family_id,
        metric_type=body.metric_type,
        value=body.value,
        unit=unit,
        device_id=body.device_id,
        device_type=body.device_type,
        location=body.location,
        measured_at=body.measured_at,
        is_alert=is_alert,
        alert_level=alert_level,
        notes=body.notes,
    )


# ══════════════════════════════════════════════════════════════════════
# 手动录入
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/records",
    response_model=EnvironmentRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="手动录入一条环境指标（含阈值超限自动标注）",
)
async def create_record(
    member_id: uuid.UUID,
    body: EnvironmentRecordCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    record = _build_record(family_id, body)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.post(
    "/{member_id}/records/batch",
    response_model=EnvironmentRecordList,
    status_code=status.HTTP_201_CREATED,
    summary="批量录入环境数据（最多 200 条）",
)
async def create_records_batch(
    member_id: uuid.UUID,
    body: list[EnvironmentRecordCreate],
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    if len(body) > 200:
        raise HTTPException(status_code=422, detail="单次最多 200 条")
    family_id = await _get_family_id(member_id, db)
    records = [_build_record(family_id, b) for b in body]
    db.add_all(records)
    await db.commit()
    for r in records:
        await db.refresh(r)
    return {"total": len(records), "items": records}


# ══════════════════════════════════════════════════════════════════════
# 查询
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/records",
    response_model=EnvironmentRecordList,
    summary="查询环境记录列表（可按指标类型/位置/时间/告警状态过滤）",
)
async def list_records(
    member_id: uuid.UUID,
    metric_type: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    is_alert: Optional[bool] = Query(None),
    hours: Optional[int] = Query(None, ge=1, le=8760, description="仅返回最近 N 小时"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    q = select(EnvironmentRecord).where(EnvironmentRecord.family_id == family_id)

    if metric_type:
        q = q.where(EnvironmentRecord.metric_type == metric_type)
    if location:
        q = q.where(EnvironmentRecord.location == location)
    if is_alert is not None:
        q = q.where(EnvironmentRecord.is_alert == is_alert)
    if hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        q = q.where(EnvironmentRecord.measured_at >= since)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    items = (await db.execute(q.order_by(desc(EnvironmentRecord.measured_at))
                               .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"total": total, "items": items}


@router.get(
    "/{member_id}/records/{record_id}",
    response_model=EnvironmentRecordOut,
    summary="获取单条环境记录详情",
)
async def get_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    r = (await db.execute(
        select(EnvironmentRecord).where(
            EnvironmentRecord.id == record_id,
            EnvironmentRecord.family_id == family_id,
        )
    )).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return r


@router.delete(
    "/{member_id}/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除环境记录",
)
async def delete_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    r = (await db.execute(
        select(EnvironmentRecord).where(
            EnvironmentRecord.id == record_id,
            EnvironmentRecord.family_id == family_id,
        )
    )).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    await db.delete(r)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 综合摘要
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/summary",
    response_model=EnvironmentSummary,
    summary="当前家庭室内环境综合摘要（最新各指标 + 空气质量等级）",
)
async def get_summary(
    member_id: uuid.UUID,
    hours: int = Query(2, ge=1, le=48, description="取最近 N 小时的数据"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 每种指标取最新一条
    sub = (
        select(EnvironmentRecord)
        .where(EnvironmentRecord.family_id == family_id, EnvironmentRecord.measured_at >= since)
    )
    all_records = (await db.execute(sub.order_by(desc(EnvironmentRecord.measured_at)))).scalars().all()

    seen: set[str] = set()
    latest: list[EnvironmentRecord] = []
    for r in all_records:
        if r.metric_type not in seen:
            seen.add(r.metric_type)
            latest.append(r)

    level = compute_air_quality_level(latest)
    alert_count = sum(1 for r in all_records if r.is_alert)

    return {
        "family_id": family_id,
        "air_quality_level": level.value,
        "record_count": len(all_records),
        "latest_records": latest,
        "alert_count": alert_count,
    }


# ══════════════════════════════════════════════════════════════════════
# LLM 环境建议
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/advice",
    response_model=EnvironmentAdviceOut,
    status_code=status.HTTP_201_CREATED,
    summary="生成环境健康 LLM 建议（基于最近 N 小时数据）",
)
async def create_advice(
    member_id: uuid.UUID,
    body: AdviceRequest,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    since = datetime.now(timezone.utc) - timedelta(hours=body.hours)

    q = (
        select(EnvironmentRecord)
        .where(EnvironmentRecord.family_id == family_id, EnvironmentRecord.measured_at >= since)
    )
    if body.location:
        q = q.where(EnvironmentRecord.location == body.location)
    all_records = (await db.execute(q.order_by(desc(EnvironmentRecord.measured_at)))).scalars().all()

    # 每种指标取最新
    seen: set[str] = set()
    latest: list[EnvironmentRecord] = []
    for r in all_records:
        if r.metric_type not in seen:
            seen.add(r.metric_type)
            latest.append(r)

    level = compute_air_quality_level(latest)

    advice_text = await generate_environment_advice(family_id, latest, level, db)

    by_type = {r.metric_type: r.value for r in latest}
    now = datetime.now(timezone.utc)
    advice = EnvironmentAdvice(
        family_id=family_id,
        air_quality_level=level.value,
        pm2_5_value=by_type.get("pm2_5"),
        co2_value=by_type.get("co2"),
        temperature_value=by_type.get("temperature"),
        humidity_value=by_type.get("humidity"),
        advice_text=advice_text,
        generated_at=now,
    )
    db.add(advice)
    await db.commit()
    await db.refresh(advice)
    return advice


@router.get(
    "/{member_id}/advice",
    response_model=list[EnvironmentAdviceOut],
    summary="查看历史环境建议列表",
)
async def list_advice(
    member_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    items = (await db.execute(
        select(EnvironmentAdvice)
        .where(EnvironmentAdvice.family_id == family_id)
        .order_by(desc(EnvironmentAdvice.generated_at))
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return list(items)


# ══════════════════════════════════════════════════════════════════════
# 传感器 Webhook 接入
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/webhook/xiaomi",
    response_model=EnvironmentRecordList,
    status_code=status.HTTP_201_CREATED,
    summary="接收小米传感器 Webhook 推送",
)
async def webhook_xiaomi(
    member_id: uuid.UUID,
    payload: XiaomiWebhookPayload,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    parsed = parse_xiaomi_payload(payload.model_dump())
    now = datetime.now(timezone.utc)
    records = []
    for item in parsed:
        is_alert, alert_level = check_threshold(item["metric_type"], item["value"])
        r = EnvironmentRecord(
            family_id=family_id,
            metric_type=item["metric_type"],
            value=item["value"],
            unit=item["unit"],
            device_id=item.get("device_id"),
            device_type="xiaomi",
            measured_at=now,
            is_alert=is_alert,
            alert_level=alert_level,
        )
        records.append(r)
    if records:
        db.add_all(records)
        await db.commit()
        for r in records:
            await db.refresh(r)
    return {"total": len(records), "items": records}


@router.post(
    "/{member_id}/webhook/home-assistant",
    response_model=EnvironmentRecordList,
    status_code=status.HTTP_201_CREATED,
    summary="接收 Home Assistant Webhook 推送",
)
async def webhook_home_assistant(
    member_id: uuid.UUID,
    payload: HomeAssistantWebhookPayload,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    family_id = await _get_family_id(member_id, db)
    parsed = parse_home_assistant_payload(payload.model_dump())
    now = datetime.now(timezone.utc)
    records = []
    for item in parsed:
        is_alert, alert_level = check_threshold(item["metric_type"], item["value"])
        r = EnvironmentRecord(
            family_id=family_id,
            metric_type=item["metric_type"],
            value=item["value"],
            unit=item["unit"],
            device_id=item.get("device_id"),
            device_type="home_assistant",
            measured_at=now,
            is_alert=is_alert,
            alert_level=alert_level,
        )
        records.append(r)
    if records:
        db.add_all(records)
        await db.commit()
        for r in records:
            await db.refresh(r)
    return {"total": len(records), "items": records}
