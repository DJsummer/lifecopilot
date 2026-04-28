"""睡眠质量分析路由 — /api/v1/sleep (T006)"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.sleep import (
    SleepRecordCreate,
    SleepRecordList,
    SleepRecordOut,
    SleepWeeklySummary,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.member import Member
from src.models.sleep import SleepRecord
from src.services.sleep_service import (
    analyze_sleep_trend,
    calculate_sleep_score,
    generate_sleep_advice,
)

log = structlog.get_logger()
router = APIRouter()


def _check(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ── 创建睡眠记录 ──────────────────────────────────────────────────────

@router.post(
    "/{member_id}/records",
    response_model=SleepRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="录入睡眠数据并自动计算评分",
)
async def create_sleep_record(
    member_id: uuid.UUID,
    body: SleepRecordCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    # 查询成员（需传给 LLM 生成建议）
    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")

    total_minutes = int((body.sleep_end - body.sleep_start).total_seconds() / 60)

    rec = SleepRecord(
        member_id=member_id,
        sleep_start=body.sleep_start,
        sleep_end=body.sleep_end,
        total_minutes=total_minutes,
        deep_sleep_minutes=body.deep_sleep_minutes,
        light_sleep_minutes=body.light_sleep_minutes,
        rem_minutes=body.rem_minutes,
        awake_minutes=body.awake_minutes,
        interruptions=body.interruptions,
        spo2_min=body.spo2_min,
        spo2_avg=body.spo2_avg,
        source=body.source,
        notes=body.notes,
    )

    # 计算评分
    score, quality, apnea_risk = calculate_sleep_score(rec)
    rec.sleep_score = score
    rec.quality = quality
    rec.apnea_risk = apnea_risk

    db.add(rec)
    await db.flush()  # 获取 rec.id

    # 趋势分析 & LLM 建议（异步，失败不影响保存）
    try:
        trend = await analyze_sleep_trend(member_id, db, n_days=7)
        advice = await generate_sleep_advice(member, rec, trend, db)
        rec.advice = advice
    except Exception as exc:
        log.warning("sleep advice generation failed: %s", exc)

    await db.commit()
    await db.refresh(rec)
    return rec


# ── 睡眠记录列表 ──────────────────────────────────────────────────────

@router.get(
    "/{member_id}/records",
    response_model=SleepRecordList,
    summary="获取睡眠记录列表（支持分页）",
)
async def list_sleep_records(
    member_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    quality: Optional[str] = Query(None, description="按质量过滤：poor/fair/good/excellent"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    base = select(SleepRecord).where(SleepRecord.member_id == member_id)
    if quality:
        base = base.where(SleepRecord.quality == quality)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(SleepRecord.sleep_start.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )).scalars().all()

    return SleepRecordList(total=total, items=list(rows))


# ── 睡眠记录详情 ──────────────────────────────────────────────────────

@router.get(
    "/{member_id}/records/{record_id}",
    response_model=SleepRecordOut,
    summary="获取单条睡眠记录详情",
)
async def get_sleep_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    rec = (await db.execute(
        select(SleepRecord).where(
            SleepRecord.id == record_id,
            SleepRecord.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="睡眠记录不存在")
    return rec


# ── 删除睡眠记录 ──────────────────────────────────────────────────────

@router.delete(
    "/{member_id}/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除睡眠记录",
)
async def delete_sleep_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    rec = (await db.execute(
        select(SleepRecord).where(
            SleepRecord.id == record_id,
            SleepRecord.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="睡眠记录不存在")
    await db.delete(rec)
    await db.commit()


# ── 近期睡眠趋势汇总 ──────────────────────────────────────────────────

@router.get(
    "/{member_id}/summary",
    response_model=SleepWeeklySummary,
    summary="近 N 天睡眠趋势汇总统计",
)
async def sleep_summary(
    member_id: uuid.UUID,
    n_days: int = Query(7, ge=1, le=90, description="统计天数"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    trend = await analyze_sleep_trend(member_id, db, n_days=n_days)
    return SleepWeeklySummary(
        count=trend.get("count", 0),
        avg_score=trend.get("avg_score"),
        avg_hours=trend.get("avg_hours", 0.0),
        poor_or_fair_count=trend.get("poor_or_fair_count", 0),
        apnea_high_count=trend.get("apnea_high_count", 0),
        min_spo2_overall=trend.get("min_spo2_overall"),
        recent_scores=trend.get("recent_scores", []),
    )
