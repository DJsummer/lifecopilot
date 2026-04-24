"""就医准备助手路由 — /api/v1/visit (T019)"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.visit import (
    HealthSnapshotItem,
    LabSnapshotItem,
    MedicationSnapshotItem,
    VisitSummaryCreate,
    VisitSummaryListItem,
    VisitSummaryResponse,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.health import HealthRecord
from src.models.medication import Medication, MedicationStatus
from src.models.member import Member
from src.models.report import LabReport
from src.models.visit import VisitSummary
from src.services.visit_service import VisitService

log = structlog.get_logger()
router = APIRouter()

_SERVICE: Optional[VisitService] = None


def _get_service() -> VisitService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = VisitService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ── 工具函数：JSON field → schema list ──────────────────────────────

def _parse_json(raw: Optional[str]) -> Optional[list]:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _build_response(vs: VisitSummary) -> VisitSummaryResponse:
    med_raw = _parse_json(vs.medications_snapshot)
    health_raw = _parse_json(vs.health_snapshot)
    lab_raw = _parse_json(vs.lab_snapshot)

    return VisitSummaryResponse(
        id=vs.id,
        member_id=vs.member_id,
        chief_complaint=vs.chief_complaint,
        symptom_duration=vs.symptom_duration,
        aggravating_factors=vs.aggravating_factors,
        relieving_factors=vs.relieving_factors,
        past_medical_history=vs.past_medical_history,
        visit_language=vs.visit_language,
        medications_snapshot=[MedicationSnapshotItem(**m) for m in med_raw] if med_raw is not None else None,
        health_snapshot=[HealthSnapshotItem(**h) for h in health_raw] if health_raw is not None else None,
        lab_snapshot=[LabSnapshotItem(**l) for l in lab_raw] if lab_raw is not None else None,
        summary_zh=vs.summary_zh,
        summary_en=vs.summary_en,
        created_at=vs.created_at.isoformat(),
    )


# ── POST /{member_id} ── 生成就诊摘要 ────────────────────────────────

@router.post(
    "/{member_id}",
    response_model=VisitSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="生成就医准备摘要",
)
async def create_visit_summary(
    body: VisitSummaryCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: VisitService = Depends(_get_service),
):
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "成员不存在"})

    # 查询活跃用药
    meds_result = await db.execute(
        select(Medication).where(
            and_(
                Medication.member_id == member_id,
                Medication.status == MedicationStatus.ACTIVE,
            )
        )
    )
    medications = meds_result.scalars().all()

    # 查询近期健康指标
    lookback_dt = datetime.now(tz=timezone.utc) - timedelta(days=body.health_lookback_days)
    records_result = await db.execute(
        select(HealthRecord).where(
            and_(
                HealthRecord.member_id == member_id,
                HealthRecord.measured_at >= lookback_dt,
            )
        )
    )
    health_records = records_result.scalars().all()

    # 查询近期检验单（最近 90 天）
    lab_lookback = datetime.now(tz=timezone.utc) - timedelta(days=90)
    from datetime import date as _date
    lab_lookback_date = lab_lookback.date()
    labs_result = await db.execute(
        select(LabReport).where(
            and_(
                LabReport.member_id == member_id,
                LabReport.report_date >= lab_lookback_date,
            )
        )
    )
    lab_reports = labs_result.scalars().all()

    # 生成摘要
    data = await svc.prepare_visit(
        member=member,
        medications=medications,
        health_records=health_records,
        lab_reports=lab_reports,
        chief_complaint=body.chief_complaint,
        symptom_duration=body.symptom_duration,
        aggravating_factors=body.aggravating_factors,
        relieving_factors=body.relieving_factors,
        past_medical_history=body.past_medical_history,
        visit_language=body.visit_language.value,
    )

    vs = VisitSummary(
        member_id=member_id,
        chief_complaint=body.chief_complaint,
        symptom_duration=body.symptom_duration,
        aggravating_factors=body.aggravating_factors,
        relieving_factors=body.relieving_factors,
        past_medical_history=body.past_medical_history,
        visit_language=body.visit_language,
        **data,
    )
    db.add(vs)
    await db.commit()
    await db.refresh(vs)

    log.info("就诊摘要已生成", visit_id=str(vs.id), language=body.visit_language.value)
    return _build_response(vs)


# ── GET /{member_id} ── 历史列表 ─────────────────────────────────────

@router.get(
    "/{member_id}",
    response_model=List[VisitSummaryListItem],
    summary="就诊摘要历史列表",
)
async def list_visit_summaries(
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitSummary)
        .where(VisitSummary.member_id == member_id)
        .order_by(VisitSummary.created_at.desc())
    )
    summaries = result.scalars().all()

    return [
        VisitSummaryListItem(
            id=vs.id,
            member_id=vs.member_id,
            chief_complaint=vs.chief_complaint,
            visit_language=vs.visit_language,
            has_summary_zh=bool(vs.summary_zh),
            has_summary_en=bool(vs.summary_en),
            created_at=vs.created_at.isoformat(),
        )
        for vs in summaries
    ]


# ── GET /{member_id}/{visit_id} ── 详情 ──────────────────────────────

@router.get(
    "/{member_id}/{visit_id}",
    response_model=VisitSummaryResponse,
    summary="就诊摘要详情",
)
async def get_visit_summary(
    visit_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    vs = await db.get(VisitSummary, visit_id)
    if vs is None or vs.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "摘要不存在"})
    return _build_response(vs)


# ── DELETE /{member_id}/{visit_id} ── 删除 ───────────────────────────

@router.delete(
    "/{member_id}/{visit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除就诊摘要",
)
async def delete_visit_summary(
    visit_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    vs = await db.get(VisitSummary, visit_id)
    if vs is None or vs.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "摘要不存在"})
    await db.delete(vs)
    await db.commit()
