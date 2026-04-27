"""运动方案路由 — /api/v1/fitness (T015)"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.fitness import (
    ExercisePlanCreate,
    ExercisePlanList,
    ExercisePlanOut,
    FitnessAssessmentCreate,
    FitnessAssessmentOut,
    WeeklySummary,
    WorkoutLogCreate,
    WorkoutLogList,
    WorkoutLogOut,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.exercise import (
    ExercisePlan,
    FitnessAssessment,
    WorkoutLog,
)
from src.models.member import Member
from src.services.fitness_service import (
    analyze_workout,
    generate_fitness_plan,
    get_weekly_summary,
)

log = structlog.get_logger()
router = APIRouter()


def _check_family(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


# ══════════════════════════════════════════════════════════════════════
# 体能评估问卷
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/assessment",
    response_model=FitnessAssessmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建/更新体能评估问卷",
)
async def upsert_assessment(
    member_id: uuid.UUID,
    body: FitnessAssessmentCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)

    # 查询目标成员
    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    # Upsert（如已存在则更新）
    stmt = select(FitnessAssessment).where(FitnessAssessment.member_id == member_id)
    assessment = (await db.execute(stmt)).scalar_one_or_none()
    if assessment is None:
        assessment = FitnessAssessment(member_id=member_id)
        db.add(assessment)

    assessment.fitness_level = body.fitness_level
    assessment.primary_goal = body.primary_goal
    assessment.available_minutes_per_session = body.available_minutes_per_session
    assessment.available_days_per_week = body.available_days_per_week
    assessment.preferred_types = json.dumps([t.value for t in body.preferred_types]) if body.preferred_types else None
    assessment.limitations = json.dumps(body.limitations) if body.limitations else None
    assessment.equipment = json.dumps(body.equipment) if body.equipment else None

    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get(
    "/{member_id}/assessment",
    response_model=FitnessAssessmentOut,
    summary="获取成员体能评估",
)
async def get_assessment(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(FitnessAssessment).where(FitnessAssessment.member_id == member_id)
    assessment = (await db.execute(stmt)).scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="尚未完成体能评估")
    return assessment


# ══════════════════════════════════════════════════════════════════════
# 运动计划
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/plans",
    response_model=ExercisePlanOut,
    status_code=status.HTTP_201_CREATED,
    summary="生成本周个性化运动计划",
)
async def create_plan(
    member_id: uuid.UUID,
    body: ExercisePlanCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)

    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    # 需要先完成体能评估
    stmt = select(FitnessAssessment).where(FitnessAssessment.member_id == member_id)
    assessment = (await db.execute(stmt)).scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=400, detail="请先完成体能评估问卷")

    week_start = body.week_start or _this_monday()
    week_end = week_start + timedelta(days=6)

    preferred = json.loads(assessment.preferred_types) if assessment.preferred_types else []
    limitations = json.loads(assessment.limitations) if assessment.limitations else []
    equipment = json.loads(assessment.equipment) if assessment.equipment else []

    result = await generate_fitness_plan(
        member=member,
        db=db,
        fitness_level=assessment.fitness_level,
        primary_goal=assessment.primary_goal,
        available_days=assessment.available_days_per_week,
        available_minutes=assessment.available_minutes_per_session,
        preferred_types=preferred,
        limitations=limitations,
        equipment=equipment,
    )

    # 将当前活跃计划设为失效（同一-member 每次生成新计划会覆盖）
    await db.execute(
        select(ExercisePlan).where(
            ExercisePlan.member_id == member_id,
            ExercisePlan.is_active == True,  # noqa: E712
        )
    )
    # SQLAlchemy 2.x 用 update
    from sqlalchemy import update
    await db.execute(
        update(ExercisePlan)
        .where(ExercisePlan.member_id == member_id, ExercisePlan.is_active == True)  # noqa: E712
        .values(is_active=False)
    )

    plan = ExercisePlan(
        fitness_assessment_id=assessment.id,
        member_id=member_id,
        week_start=week_start,
        week_end=week_end,
        plan_data=json.dumps(result.get("week_plan"), ensure_ascii=False),
        llm_summary=result.get("summary"),
        is_active=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get(
    "/{member_id}/plans",
    response_model=ExercisePlanList,
    summary="获取运动计划列表（最新在前）",
)
async def list_plans(
    member_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    total = (await db.execute(
        select(func.count()).select_from(ExercisePlan).where(ExercisePlan.member_id == member_id)
    )).scalar_one()
    items = (await db.execute(
        select(ExercisePlan)
        .where(ExercisePlan.member_id == member_id)
        .order_by(ExercisePlan.week_start.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()
    return {"total": total, "items": list(items)}


@router.get(
    "/{member_id}/plans/active",
    response_model=ExercisePlanOut,
    summary="获取当前活跃运动计划",
)
async def get_active_plan(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(ExercisePlan).where(
        ExercisePlan.member_id == member_id,
        ExercisePlan.is_active == True,  # noqa: E712
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="暂无活跃运动计划")
    return plan


# ══════════════════════════════════════════════════════════════════════
# 运动日志
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/logs",
    response_model=WorkoutLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="记录一次运动日志（LLM 估算热量 + 给出反馈）",
)
async def create_workout_log(
    member_id: uuid.UUID,
    body: WorkoutLogCreate,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)

    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    # LLM 分析
    from src.models.health import HealthRecord, MetricType
    weight_row = (await db.execute(
        select(HealthRecord)
        .where(HealthRecord.member_id == member_id, HealthRecord.metric_type == MetricType.WEIGHT)
        .order_by(HealthRecord.measured_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    weight_kg = weight_row.value if weight_row else 70.0

    analysis = await analyze_workout(
        exercise_type=body.exercise_type,
        exercise_name=body.exercise_name,
        duration_minutes=body.duration_minutes or 30,
        weight_kg=weight_kg,
        avg_heart_rate=body.avg_heart_rate,
        notes=body.notes,
    )

    wlog = WorkoutLog(
        member_id=member_id,
        exercise_plan_id=body.exercise_plan_id,
        log_date=body.log_date,
        exercise_type=body.exercise_type,
        exercise_name=body.exercise_name,
        duration_minutes=body.duration_minutes,
        calories_burned=analysis["calories_burned"],
        avg_heart_rate=body.avg_heart_rate,
        max_heart_rate=body.max_heart_rate,
        status=body.status,
        notes=body.notes,
        llm_feedback=analysis["llm_feedback"],
    )
    db.add(wlog)
    await db.commit()
    await db.refresh(wlog)
    return wlog


@router.get(
    "/{member_id}/logs",
    response_model=WorkoutLogList,
    summary="获取运动日志列表",
)
async def list_workout_logs(
    member_id: uuid.UUID,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    q = select(WorkoutLog).where(WorkoutLog.member_id == member_id)
    if start_date:
        q = q.where(WorkoutLog.log_date >= start_date)
    if end_date:
        q = q.where(WorkoutLog.log_date <= end_date)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    items = (await db.execute(
        q.order_by(WorkoutLog.log_date.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "items": list(items)}


@router.get(
    "/{member_id}/logs/{log_id}",
    response_model=WorkoutLogOut,
    summary="获取单条运动日志",
)
async def get_workout_log(
    member_id: uuid.UUID,
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(WorkoutLog).where(WorkoutLog.id == log_id, WorkoutLog.member_id == member_id)
    wlog = (await db.execute(stmt)).scalar_one_or_none()
    if not wlog:
        raise HTTPException(status_code=404, detail="日志不存在")
    return wlog


@router.delete(
    "/{member_id}/logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除运动日志",
)
async def delete_workout_log(
    member_id: uuid.UUID,
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    stmt = select(WorkoutLog).where(WorkoutLog.id == log_id, WorkoutLog.member_id == member_id)
    wlog = (await db.execute(stmt)).scalar_one_or_none()
    if not wlog:
        raise HTTPException(status_code=404, detail="日志不存在")
    await db.delete(wlog)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 每周汇总
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/{member_id}/summary/weekly",
    response_model=WeeklySummary,
    summary="获取某周运动汇总统计",
)
async def weekly_summary(
    member_id: uuid.UUID,
    week_start: Optional[date] = Query(None, description="周一日期，不传则默认本周"),
    db: AsyncSession = Depends(get_db),
    current: Member = Depends(get_current_member),
):
    _check_family(member_id, current)
    ws = week_start or _this_monday()
    return await get_weekly_summary(member_id=member_id, week_start=ws, db=db)
