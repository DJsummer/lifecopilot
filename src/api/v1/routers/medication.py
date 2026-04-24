"""用药管理路由 — /api/v1/medications (T020)"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.v1.schemas.medication import (
    AdherenceLogCreate,
    AdherenceLogResponse,
    AdherenceStatsResponse,
    InteractionCheckRequest,
    InteractionCheckResponse,
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
    ReminderResponse,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.medication import (
    AdherenceLog,
    AdherenceStatus,
    Medication,
    MedicationReminder,
    MedicationStatus,
)
from src.models.member import Member
from src.services.medication_service import MedicationService

log = structlog.get_logger()
router = APIRouter()

_SERVICE: Optional[MedicationService] = None


def _get_service() -> MedicationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = MedicationService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _to_response(med: Medication) -> MedicationResponse:
    return MedicationResponse(
        id=med.id,
        member_id=med.member_id,
        name=med.name,
        generic_name=med.generic_name,
        dosage=med.dosage,
        frequency=med.frequency,
        instructions=med.instructions,
        start_date=med.start_date,
        end_date=med.end_date,
        status=med.status,
        llm_description=med.llm_description,
        reminders=[
            ReminderResponse(id=r.id, remind_time=r.remind_time, is_active=r.is_active)
            for r in (med.reminders or [])
        ],
        created_at=med.created_at.isoformat() if med.created_at else None,
    )


# ── POST /{member_id} — 新增用药方案 ──────────────────────────────────
@router.post(
    "/{member_id}",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增用药方案",
    description="添加用药方案，系统自动用 LLM 生成药物通俗说明（可跳过）。",
)
async def create_medication(
    body: MedicationCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: MedicationService = Depends(_get_service),
):
    # LLM 解释（失败时静默降级，不阻塞保存）
    llm_description: Optional[str] = None
    try:
        llm_result = await svc.explain_medication(body.name, body.dosage)
        llm_description = svc.format_description(llm_result)
    except Exception as e:
        log.warning("medication LLM explain failed, skipping", error=str(e))

    med = Medication(
        member_id=member_id,
        name=body.name,
        generic_name=body.generic_name,
        dosage=body.dosage,
        frequency=body.frequency,
        instructions=body.instructions,
        start_date=body.start_date,
        end_date=body.end_date,
        status=MedicationStatus.ACTIVE,
        llm_description=llm_description,
    )
    db.add(med)
    await db.flush()  # 获取 med.id，用于关联 reminders

    for t in body.reminder_times:
        db.add(MedicationReminder(medication_id=med.id, remind_time=t))

    await db.commit()

    # 重新加载含 reminders 的对象
    stmt = (
        select(Medication)
        .where(Medication.id == med.id)
        .options(selectinload(Medication.reminders))
    )
    result = await db.execute(stmt)
    med = result.scalar_one()

    log.info("medication created", member_id=str(member_id), name=body.name)
    return _to_response(med)


# ── GET /{member_id} — 列表 ───────────────────────────────────────────
@router.get(
    "/{member_id}",
    response_model=List[MedicationResponse],
    summary="获取用药方案列表",
)
async def list_medications(
    member_id: uuid.UUID = Depends(_member_id_param),
    medication_status: Optional[str] = Query(None, alias="status", description="active/paused/completed"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Medication)
        .where(Medication.member_id == member_id)
        .options(selectinload(Medication.reminders))
        .order_by(Medication.start_date.desc())
    )
    if medication_status:
        stmt = stmt.where(Medication.status == medication_status)

    result = await db.execute(stmt)
    return [_to_response(m) for m in result.scalars().all()]


# ── GET /{member_id}/{med_id} — 详情 ─────────────────────────────────
@router.get(
    "/{member_id}/{med_id}",
    response_model=MedicationResponse,
    summary="获取用药方案详情",
)
async def get_medication(
    med_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Medication)
        .where(Medication.id == med_id, Medication.member_id == member_id)
        .options(selectinload(Medication.reminders))
    )
    result = await db.execute(stmt)
    med = result.scalar_one_or_none()
    if med is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"},
        )
    return _to_response(med)


# ── PATCH /{member_id}/{med_id} — 更新 ───────────────────────────────
@router.patch(
    "/{member_id}/{med_id}",
    response_model=MedicationResponse,
    summary="更新用药方案",
)
async def update_medication(
    med_id: uuid.UUID,
    body: MedicationUpdate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Medication)
        .where(Medication.id == med_id, Medication.member_id == member_id)
        .options(selectinload(Medication.reminders))
    )
    result = await db.execute(stmt)
    med = result.scalar_one_or_none()
    if med is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"},
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(med, field, value)

    await db.commit()
    await db.refresh(med)

    # 重新加载 reminders
    stmt2 = (
        select(Medication)
        .where(Medication.id == med_id)
        .options(selectinload(Medication.reminders))
    )
    r2 = await db.execute(stmt2)
    med = r2.scalar_one()
    return _to_response(med)


# ── DELETE /{member_id}/{med_id} — 删除 ──────────────────────────────
@router.delete(
    "/{member_id}/{med_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除用药方案",
)
async def delete_medication(
    med_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"},
        )
    await db.delete(med)
    await db.commit()
    log.info("medication deleted", med_id=str(med_id))


# ── POST /{member_id}/{med_id}/reminders — 添加提醒 ──────────────────
@router.post(
    "/{member_id}/{med_id}/reminders",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="添加服药提醒时间",
)
async def add_reminder(
    med_id: uuid.UUID,
    remind_time: str = Query(..., description="提醒时间，格式 HH:MM"),
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    import re
    if not re.match(r"^\d{2}:\d{2}$", remind_time):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_TIME", "message": "时间格式应为 HH:MM"},
        )
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"},
        )
    reminder = MedicationReminder(medication_id=med_id, remind_time=remind_time)
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return ReminderResponse(id=reminder.id, remind_time=reminder.remind_time, is_active=reminder.is_active)


# ── DELETE /{member_id}/{med_id}/reminders/{rid} ──────────────────────
@router.delete(
    "/{member_id}/{med_id}/reminders/{rid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除服药提醒",
)
async def delete_reminder(
    med_id: uuid.UUID,
    rid: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"})
    reminder = await db.get(MedicationReminder, rid)
    if reminder is None or reminder.medication_id != med_id:
        raise HTTPException(status_code=404, detail={"code": "REMINDER_NOT_FOUND", "message": "提醒不存在"})
    await db.delete(reminder)
    await db.commit()


# ── POST /{member_id}/{med_id}/adherence — 记录依从性 ─────────────────
@router.post(
    "/{member_id}/{med_id}/adherence",
    response_model=AdherenceLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="记录服药依从性",
)
async def log_adherence(
    med_id: uuid.UUID,
    body: AdherenceLogCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"})

    delay_minutes: Optional[int] = None
    if body.status == AdherenceStatus.DELAYED and body.actual_at and body.scheduled_at:
        diff = (body.actual_at - body.scheduled_at).total_seconds() / 60
        delay_minutes = max(0, int(diff))

    log_entry = AdherenceLog(
        medication_id=med_id,
        scheduled_at=body.scheduled_at,
        actual_at=body.actual_at,
        status=body.status,
        notes=body.notes,
        delay_minutes=delay_minutes,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)

    return AdherenceLogResponse(
        id=log_entry.id,
        medication_id=log_entry.medication_id,
        scheduled_at=log_entry.scheduled_at,
        actual_at=log_entry.actual_at,
        status=log_entry.status,
        notes=log_entry.notes,
        delay_minutes=log_entry.delay_minutes,
        created_at=log_entry.created_at.isoformat() if log_entry.created_at else None,
    )


# ── GET /{member_id}/{med_id}/adherence — 依从性历史 ──────────────────
@router.get(
    "/{member_id}/{med_id}/adherence",
    response_model=List[AdherenceLogResponse],
    summary="获取服药依从性记录",
)
async def get_adherence(
    med_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"})

    stmt = (
        select(AdherenceLog)
        .where(AdherenceLog.medication_id == med_id)
        .order_by(AdherenceLog.scheduled_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        AdherenceLogResponse(
            id=l.id,
            medication_id=l.medication_id,
            scheduled_at=l.scheduled_at,
            actual_at=l.actual_at,
            status=l.status,
            notes=l.notes,
            delay_minutes=l.delay_minutes,
            created_at=l.created_at.isoformat() if l.created_at else None,
        )
        for l in logs
    ]


# ── GET /{member_id}/{med_id}/adherence/stats — 依从性统计 ────────────
@router.get(
    "/{member_id}/{med_id}/adherence/stats",
    response_model=AdherenceStatsResponse,
    summary="获取服药依从性统计",
)
async def get_adherence_stats(
    med_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    med = await db.get(Medication, med_id)
    if med is None or med.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "MEDICATION_NOT_FOUND", "message": "用药方案不存在"})

    stmt = select(AdherenceLog).where(AdherenceLog.medication_id == med_id)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    taken = sum(1 for l in logs if l.status == AdherenceStatus.TAKEN)
    missed = sum(1 for l in logs if l.status == AdherenceStatus.MISSED)
    delayed = sum(1 for l in logs if l.status == AdherenceStatus.DELAYED)
    skipped = sum(1 for l in logs if l.status == AdherenceStatus.SKIPPED)
    total = len(logs)
    adherence_rate = round(taken / total, 4) if total > 0 else 0.0

    return AdherenceStatsResponse(
        medication_id=med_id,
        total_logs=total,
        taken=taken,
        missed=missed,
        delayed=delayed,
        skipped=skipped,
        adherence_rate=adherence_rate,
    )


# ── POST /{member_id}/interaction-check — 药物相互作用检查 ────────────
@router.post(
    "/{member_id}/interaction-check",
    response_model=InteractionCheckResponse,
    summary="药物相互作用风险检查",
    description="传入至少 2 种药物名称，AI 检查是否存在相互作用风险。",
)
async def check_interactions(
    body: InteractionCheckRequest,
    member_id: uuid.UUID = Depends(_member_id_param),
    svc: MedicationService = Depends(_get_service),
):
    result = await svc.check_interactions(body.medication_names)
    return InteractionCheckResponse(
        medications=body.medication_names,
        has_interaction=result.get("has_interaction", False),
        risk_level=result.get("risk_level", "none"),
        interactions=result.get("interactions", []),
        summary=result.get("summary", ""),
        advice=result.get("advice", ""),
        disclaimer=result.get("disclaimer", "本分析仅供参考，请告知医生或药师您正在服用的所有药物。"),
    )
