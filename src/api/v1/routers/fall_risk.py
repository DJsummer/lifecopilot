"""老人跌倒风险评估路由 — /api/v1/fall-risk (T008)"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.fall_risk import (
    FallRiskAssessmentCreate,
    FallRiskAssessmentOut,
    FallRiskList,
    FallRiskSummary,
    InactivityCheckRequest,
    InactivityLogList,
    InactivityLogOut,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.fall_risk import FallRiskAssessment, InactivityLog
from src.models.member import Member
from src.services.fall_risk_service import (
    compute_fall_risk_score,
    detect_inactivity,
    generate_fall_risk_recommendations,
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


def _calc_age(member: Member, ref: "datetime") -> Optional[int]:
    if not member.birth_date:
        return None
    from datetime import date
    rd = ref.date() if hasattr(ref, "date") else ref
    age = (rd.year - member.birth_date.year) - (
        (rd.month, rd.day) < (member.birth_date.month, member.birth_date.day)
    )
    return age


# ══════════════════════════════════════════════════════════════════════
# 跌倒风险评估 CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/assessments",
    response_model=FallRiskAssessmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="提交跌倒风险问卷，自动评分 + LLM 干预建议",
)
async def create_assessment(
    member_id: uuid.UUID,
    body: FallRiskAssessmentCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    member = await _get_member(member_id, db)

    age = _calc_age(member, body.assessed_at)

    assessment = FallRiskAssessment(
        member_id=member_id,
        assessed_at=body.assessed_at,
        has_fall_history=body.has_fall_history,
        has_osteoporosis=body.has_osteoporosis,
        has_neurological_disease=body.has_neurological_disease,
        uses_sedatives=body.uses_sedatives,
        has_gait_disorder=body.has_gait_disorder,
        uses_walking_aid=body.uses_walking_aid,
        has_vision_impairment=body.has_vision_impairment,
        has_weakness_or_balance_issue=body.has_weakness_or_balance_issue,
        lives_alone=body.lives_alone,
        frequent_nocturia=body.frequent_nocturia,
        has_urge_incontinence=body.has_urge_incontinence,
        age_at_assessment=age,
        notes=body.notes,
    )

    # 评分
    score, level = compute_fall_risk_score(assessment, age)
    assessment.total_score = score
    assessment.risk_level = level

    db.add(assessment)
    await db.flush()

    # LLM 建议（失败不影响保存）
    try:
        recs = await generate_fall_risk_recommendations(member, assessment, db)
        assessment.recommendations = recs
    except Exception as exc:
        log.warning("fall risk LLM failed: %s", exc)

    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get(
    "/{member_id}/assessments",
    response_model=FallRiskList,
    summary="评估记录列表（按时间倒序）",
)
async def list_assessments(
    member_id: uuid.UUID,
    risk_level: Optional[str] = Query(None, description="按风险等级过滤：low/moderate/high/very_high"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    base = select(FallRiskAssessment).where(FallRiskAssessment.member_id == member_id)
    if risk_level:
        base = base.where(FallRiskAssessment.risk_level == risk_level)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(FallRiskAssessment.assessed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )).scalars().all()
    return FallRiskList(total=total, items=list(rows))


@router.get(
    "/{member_id}/assessments/latest",
    response_model=FallRiskAssessmentOut,
    summary="获取最新一次跌倒风险评估",
)
async def get_latest_assessment(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    rec = (await db.execute(
        select(FallRiskAssessment)
        .where(FallRiskAssessment.member_id == member_id)
        .order_by(FallRiskAssessment.assessed_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="暂无跌倒风险评估记录")
    return rec


@router.get(
    "/{member_id}/assessments/{assessment_id}",
    response_model=FallRiskAssessmentOut,
    summary="评估记录详情",
)
async def get_assessment(
    member_id: uuid.UUID,
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    rec = (await db.execute(
        select(FallRiskAssessment).where(
            FallRiskAssessment.id == assessment_id,
            FallRiskAssessment.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    return rec


@router.delete(
    "/{member_id}/assessments/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除评估记录",
)
async def delete_assessment(
    member_id: uuid.UUID,
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    rec = (await db.execute(
        select(FallRiskAssessment).where(
            FallRiskAssessment.id == assessment_id,
            FallRiskAssessment.member_id == member_id,
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    await db.delete(rec)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 不活动检测
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/inactivity/check",
    response_model=Optional[InactivityLogOut],
    summary="触发不活动检测（基于最近健康记录时间），超阈则记录告警",
)
async def check_inactivity(
    member_id: uuid.UUID,
    body: InactivityCheckRequest,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    await _get_member(member_id, db)
    log_entry = await detect_inactivity(
        member_id, db,
        threshold_hours=body.threshold_hours,
        alert_contact=body.alert_contact,
    )
    if log_entry:
        await db.commit()
        await db.refresh(log_entry)
        return log_entry
    return None


@router.get(
    "/{member_id}/inactivity",
    response_model=InactivityLogList,
    summary="不活动记录列表",
)
async def list_inactivity_logs(
    member_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)
    base = select(InactivityLog).where(InactivityLog.member_id == member_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(InactivityLog.period_start.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )).scalars().all()
    return InactivityLogList(total=total, items=list(rows))


# ══════════════════════════════════════════════════════════════════════
# 综合概览
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/summary",
    response_model=FallRiskSummary,
    summary="跌倒风险综合概览",
)
async def fall_risk_summary(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check(member_id, current)

    latest = (await db.execute(
        select(FallRiskAssessment)
        .where(FallRiskAssessment.member_id == member_id)
        .order_by(FallRiskAssessment.assessed_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    assessment_count = (await db.execute(
        select(func.count()).where(FallRiskAssessment.member_id == member_id)
    )).scalar_one()

    inactivity_count = (await db.execute(
        select(func.count()).where(InactivityLog.member_id == member_id)
    )).scalar_one()

    latest_inactivity = (await db.execute(
        select(InactivityLog)
        .where(InactivityLog.member_id == member_id)
        .order_by(InactivityLog.period_start.desc())
        .limit(1)
    )).scalar_one_or_none()

    return FallRiskSummary(
        assessment_count=assessment_count,
        latest_assessment=FallRiskAssessmentOut.model_validate(latest) if latest else None,
        inactivity_log_count=inactivity_count,
        recent_inactivity_hours=latest_inactivity.duration_hours if latest_inactivity else None,
    )
