"""营养规划路由 — /api/v1/nutrition (T014)"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.nutrition import (
    DailyIntakeSummary,
    DietLogCreate,
    DietLogList,
    DietLogOut,
    FoodSearchResult,
    MealPlanList,
    MealPlanOut,
    NutritionGoalCreate,
    NutritionGoalOut,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.member import Member
from src.models.nutrition import DietLog, FoodItem, MealPlan, NutritionGoal
from src.services.nutrition_service import (
    analyze_diet_log,
    generate_meal_plan,
    generate_nutrition_goal,
)

log = structlog.get_logger()
router = APIRouter()


def _check_family(member_id: uuid.UUID, current: Member = Depends(get_current_member)) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ══════════════════════════════════════════════════════════════════════
# 食物营养素数据库
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/foods",
    response_model=FoodSearchResult,
    summary="搜索食物营养素数据库",
)
async def search_foods(
    q: Optional[str] = Query(None, description="食物名称关键字（模糊搜索）"),
    category: Optional[str] = Query(None, description="分类过滤（谷物/蔬菜/水果/肉类等）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: Member = Depends(get_current_member),  # 需要登录
):
    stmt = select(FoodItem).where(FoodItem.is_active == True)  # noqa: E712
    if q:
        stmt = stmt.where(FoodItem.name.ilike(f"%{q}%"))
    if category:
        stmt = stmt.where(FoodItem.category == category)
    stmt = stmt.order_by(FoodItem.name)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return FoodSearchResult(total=total, items=list(rows))


# ══════════════════════════════════════════════════════════════════════
# 营养目标
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/goal",
    response_model=NutritionGoalOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建或更新成员营养目标（LLM 个性化生成）",
)
async def create_or_update_goal(
    body: NutritionGoalCreate,
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    # 查询成员
    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    # LLM 生成营养目标
    goal_data = await generate_nutrition_goal(
        member=member,
        db=db,
        diet_type=body.diet_type.value,
        allergies=body.allergies or [],
        dietary_restrictions=body.dietary_restrictions or [],
    )

    # 查是否已有目标（upsert）
    existing = (await db.execute(
        select(NutritionGoal).where(NutritionGoal.member_id == member_id)
    )).scalar_one_or_none()

    if existing:
        existing.diet_type = body.diet_type
        existing.allergies = json.dumps(body.allergies, ensure_ascii=False) if body.allergies else None
        existing.dietary_restrictions = json.dumps(body.dietary_restrictions, ensure_ascii=False) if body.dietary_restrictions else None
        for k, v in goal_data.items():
            setattr(existing, k, v)
        await db.commit()
        await db.refresh(existing)
        return existing

    goal = NutritionGoal(
        member_id=member_id,
        diet_type=body.diet_type,
        allergies=json.dumps(body.allergies, ensure_ascii=False) if body.allergies else None,
        dietary_restrictions=json.dumps(body.dietary_restrictions, ensure_ascii=False) if body.dietary_restrictions else None,
        **goal_data,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    log.info("营养目标已生成", member_id=str(member_id), calories=goal.daily_calories)
    return goal


@router.get(
    "/{member_id}/goal",
    response_model=NutritionGoalOut,
    summary="获取成员营养目标",
)
async def get_goal(
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    goal = (await db.execute(
        select(NutritionGoal).where(NutritionGoal.member_id == member_id)
    )).scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="尚未设置营养目标，请先调用 POST /{member_id}/goal")
    return goal


# ══════════════════════════════════════════════════════════════════════
# 每周食谱
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/meal-plans",
    response_model=MealPlanOut,
    status_code=status.HTTP_201_CREATED,
    summary="生成本周食谱（LLM，基于营养目标）",
)
async def create_meal_plan(
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    # 必须先有营养目标
    goal = (await db.execute(
        select(NutritionGoal).where(NutritionGoal.member_id == member_id)
    )).scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=400, detail="请先创建营养目标（POST /{member_id}/goal）")

    member = (await db.execute(select(Member).where(Member.id == member_id))).scalar_one_or_none()

    # 本周一到周日
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    allergies = json.loads(goal.allergies) if goal.allergies else []
    restrictions = json.loads(goal.dietary_restrictions) if goal.dietary_restrictions else []

    plan_data = await generate_meal_plan(
        member=member,
        db=db,
        diet_type=goal.diet_type.value if hasattr(goal.diet_type, "value") else goal.diet_type,
        allergies=allergies,
        dietary_restrictions=restrictions,
        daily_calories=goal.daily_calories or 2000,
    )

    plan = MealPlan(
        nutrition_goal_id=goal.id,
        member_id=member_id,
        week_start=week_start,
        week_end=week_end,
        **plan_data,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    log.info("食谱已生成", member_id=str(member_id), week_start=str(week_start))
    return plan


@router.get(
    "/{member_id}/meal-plans",
    response_model=MealPlanList,
    summary="获取食谱历史列表",
)
async def list_meal_plans(
    member_id: uuid.UUID = Depends(_check_family),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MealPlan).where(MealPlan.member_id == member_id).order_by(MealPlan.week_start.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return MealPlanList(total=total, items=list(rows))


@router.get(
    "/{member_id}/meal-plans/{plan_id}",
    response_model=MealPlanOut,
    summary="获取食谱详情",
)
async def get_meal_plan(
    plan_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(MealPlan).where(MealPlan.id == plan_id, MealPlan.member_id == member_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="食谱不存在")
    return row


@router.delete(
    "/{member_id}/meal-plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除食谱",
)
async def delete_meal_plan(
    plan_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(MealPlan).where(MealPlan.id == plan_id, MealPlan.member_id == member_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="食谱不存在")
    await db.delete(row)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# 饮食日志
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/{member_id}/diet-logs",
    response_model=DietLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="记录饮食（LLM 估算营养素 + 反馈）",
)
async def create_diet_log(
    body: DietLogCreate,
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    # LLM 估算
    estimated = await analyze_diet_log(body.description, body.meal_type.value)

    record = DietLog(
        member_id=member_id,
        log_date=body.log_date,
        meal_type=body.meal_type,
        description=body.description,
        **estimated,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get(
    "/{member_id}/diet-logs",
    response_model=DietLogList,
    summary="获取饮食日志列表",
)
async def list_diet_logs(
    member_id: uuid.UUID = Depends(_check_family),
    log_date: Optional[date] = Query(None, description="按日期过滤（YYYY-MM-DD）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DietLog).where(DietLog.member_id == member_id)
    if log_date:
        stmt = stmt.where(DietLog.log_date == log_date)
    stmt = stmt.order_by(DietLog.log_date.desc(), DietLog.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return DietLogList(total=total, items=list(rows))


@router.get(
    "/{member_id}/diet-logs/summary",
    response_model=DailyIntakeSummary,
    summary="获取指定日期的营养摄入汇总",
)
async def daily_summary(
    member_id: uuid.UUID = Depends(_check_family),
    log_date: date = Query(..., description="日期（YYYY-MM-DD）"),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(DietLog).where(DietLog.member_id == member_id, DietLog.log_date == log_date)
    )).scalars().all()

    def _sum(attr):
        vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return round(sum(vals), 1) if vals else None

    return DailyIntakeSummary(
        log_date=log_date,
        total_calories=_sum("estimated_calories"),
        total_protein=_sum("estimated_protein"),
        total_fat=_sum("estimated_fat"),
        total_carbohydrate=_sum("estimated_carbohydrate"),
        meal_count=len(rows),
    )


@router.delete(
    "/{member_id}/diet-logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除饮食记录",
)
async def delete_diet_log(
    log_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_check_family),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(DietLog).where(DietLog.id == log_id, DietLog.member_id == member_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    await db.delete(row)
    await db.commit()
