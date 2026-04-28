"""儿童生长发育评估路由 — /api/v1/growth (T007)"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.growth import (
    GrowthRecordCreate,
    GrowthRecordList,
    GrowthRecordOut,
    GrowthSummary,
    MilestoneAchieve,
    MilestoneCreate,
    MilestoneList,
    MilestoneOut,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.growth import DevelopmentMilestone, GrowthRecord, MilestoneStatus
from src.models.member import Member, Gender
from src.services.growth_service import (
    compute_growth_percentiles,
    generate_growth_assessment,
    init_preset_milestones,
    _compute_age_months,
)

log = structlog.get_logger()
router = APIRouter()


def _check(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


async def _get_member(member_id: uuid.UUID, db: AsyncSession) -> Member:
    m = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    return m


def _is_male(member: Member) -> bool:
    """未设置性别时默认 True（WHO 参数均有，不影响功能）"""
    if member.gender is None:
        return True
    g = member.gender.value if hasattr(member.gender, "value") else member.gender
    return g == "male"


# ══════════════════════════════════════════════════════════════════════
# 生长记录 CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/records",
    response_model=GrowthRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="录入生长测量数据（自动计算 WHO 百分位 + LLM 评估）",
)
async def create_growth_record(
    member_id: uuid.UUID,
    body: GrowthRecordCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    member = await _get_member(member_id, db)

    # 计算月龄
    age_months: Optional[int] = None
    if member.birth_date:
        age_months = _compute_age_months(member.birth_date, body.measured_at)

    # 百分位计算
    percentiles: dict = {}
    if age_months is not None and age_months <= 60:
        percentiles = compute_growth_percentiles(
            body.height_cm, body.weight_kg, age_months, _is_male(member)
        )
    elif body.height_cm and body.weight_kg:
        bmi = body.weight_kg / ((body.height_cm / 100) ** 2)
        percentiles["bmi"] = round(bmi, 1)

    rec = GrowthRecord(
        member_id=member_id,
        measured_at=body.measured_at,
        height_cm=body.height_cm,
        weight_kg=body.weight_kg,
        head_circumference_cm=body.head_circumference_cm,
        age_months=age_months,
        notes=body.notes,
        **{k: v for k, v in percentiles.items() if v is not None},
    )
    db.add(rec)
    await db.flush()

    # LLM 评估（失败不影响保存）
    try:
        assessment = await generate_growth_assessment(member, rec, db)
        rec.assessment = assessment
    except Exception as exc:
        log.warning("growth assessment failed: %s", exc)

    await db.commit()
    await db.refresh(rec)
    return rec


@router.get(
    "/{member_id}/records",
    response_model=GrowthRecordList,
    summary="生长记录列表（按测量日期倒序）",
)
async def list_growth_records(
    member_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    base = select(GrowthRecord).where(GrowthRecord.member_id == member_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(GrowthRecord.measured_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )).scalars().all()
    return GrowthRecordList(total=total, items=list(rows))


@router.get(
    "/{member_id}/records/{record_id}",
    response_model=GrowthRecordOut,
    summary="生长记录详情",
)
async def get_growth_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    rec = (await db.execute(
        select(GrowthRecord).where(
            GrowthRecord.id == record_id,
            GrowthRecord.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="生长记录不存在")
    return rec


@router.delete(
    "/{member_id}/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除生长记录",
)
async def delete_growth_record(
    member_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    rec = (await db.execute(
        select(GrowthRecord).where(
            GrowthRecord.id == record_id,
            GrowthRecord.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="生长记录不存在")
    await db.delete(rec)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 发育里程碑
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/milestones/init",
    status_code=status.HTTP_201_CREATED,
    summary="初始化系统预设发育里程碑（幂等，重复调用不重复插入）",
)
async def init_milestones(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    await _get_member(member_id, db)
    count = await init_preset_milestones(member_id, db)
    await db.commit()
    return {"inserted": count, "message": f"新增 {count} 条预设里程碑"}


@router.post(
    "/{member_id}/milestones",
    response_model=MilestoneOut,
    status_code=status.HTTP_201_CREATED,
    summary="添加自定义里程碑",
)
async def create_milestone(
    member_id: uuid.UUID,
    body: MilestoneCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    await _get_member(member_id, db)

    m = DevelopmentMilestone(
        member_id=member_id,
        milestone_type=body.milestone_type,
        title=body.title,
        typical_age_start=body.typical_age_start,
        typical_age_end=body.typical_age_end,
        status=MilestoneStatus.IN_PROGRESS.value,
        is_preset=False,
        notes=body.notes,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@router.get(
    "/{member_id}/milestones",
    response_model=MilestoneList,
    summary="发育里程碑列表（可按类型/状态过滤）",
)
async def list_milestones(
    member_id: uuid.UUID,
    milestone_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    base = select(DevelopmentMilestone).where(DevelopmentMilestone.member_id == member_id)
    if milestone_type:
        base = base.where(DevelopmentMilestone.milestone_type == milestone_type)
    if status_filter:
        base = base.where(DevelopmentMilestone.status == status_filter)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(DevelopmentMilestone.typical_age_start.asc())
    )).scalars().all()
    return MilestoneList(total=total, items=list(rows))


@router.patch(
    "/{member_id}/milestones/{milestone_id}/achieve",
    response_model=MilestoneOut,
    summary="标记里程碑为已达成",
)
async def achieve_milestone(
    member_id: uuid.UUID,
    milestone_id: uuid.UUID,
    body: MilestoneAchieve,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    member = await _get_member(member_id, db)

    m = (await db.execute(
        select(DevelopmentMilestone).where(
            DevelopmentMilestone.id == milestone_id,
            DevelopmentMilestone.member_id == member_id,
        )
    )).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="里程碑不存在")

    m.status = MilestoneStatus.ACHIEVED.value
    m.achieved_at = body.achieved_at
    if body.notes:
        m.notes = body.notes
    # 计算达成月龄
    if member.birth_date:
        m.achieved_age_months = _compute_age_months(member.birth_date, body.achieved_at)

    await db.commit()
    await db.refresh(m)
    return m


@router.delete(
    "/{member_id}/milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除里程碑（仅限自定义，预设里程碑不可删除）",
)
async def delete_milestone(
    member_id: uuid.UUID,
    milestone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    m = (await db.execute(
        select(DevelopmentMilestone).where(
            DevelopmentMilestone.id == milestone_id,
            DevelopmentMilestone.member_id == member_id,
        )
    )).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    if m.is_preset:
        raise HTTPException(status_code=403, detail="预设里程碑不可删除，可标记为已达成或忽略")
    await db.delete(m)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/summary",
    response_model=GrowthSummary,
    summary="生长发育概览（最近记录 + 里程碑统计）",
)
async def growth_summary(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    # 最近一条生长记录
    latest_rec = (await db.execute(
        select(GrowthRecord)
        .where(GrowthRecord.member_id == member_id)
        .order_by(GrowthRecord.measured_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    record_count = (await db.execute(
        select(func.count()).where(GrowthRecord.member_id == member_id)
    )).scalar_one()

    # 里程碑统计
    milestone_total = (await db.execute(
        select(func.count()).where(DevelopmentMilestone.member_id == member_id)
    )).scalar_one()
    milestone_achieved = (await db.execute(
        select(func.count()).where(
            DevelopmentMilestone.member_id == member_id,
            DevelopmentMilestone.status == MilestoneStatus.ACHIEVED.value,
        )
    )).scalar_one()
    milestone_delayed = (await db.execute(
        select(func.count()).where(
            DevelopmentMilestone.member_id == member_id,
            DevelopmentMilestone.status == MilestoneStatus.DELAYED.value,
        )
    )).scalar_one()

    return GrowthSummary(
        record_count=record_count,
        latest_record=GrowthRecordOut.model_validate(latest_rec) if latest_rec else None,
        milestone_total=milestone_total,
        milestone_achieved=milestone_achieved,
        milestone_delayed=milestone_delayed,
    )
