"""健康周报/月报路由 — /api/v1/reports (T018)"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.report import (
    HealthReportListItem,
    HealthReportResponse,
    MetricStatItem,
    MedicationStatItem,
    NotableEvent,
    ReportGenerateRequest,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.health import HealthRecord
from src.models.medication import AdherenceLog, Medication, MedicationStatus
from src.models.member import Member
from src.models.report import HealthReport, ReportPeriod, ReportStatus
from src.services.report_service import ReportService

log = structlog.get_logger()
router = APIRouter()

_SERVICE: Optional[ReportService] = None


def _get_service() -> ReportService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ReportService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


# ── 工具函数：ORM → Response ─────────────────────────────────────────

def _parse_json_field(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _build_response(rpt: HealthReport) -> HealthReportResponse:
    metric_raw = _parse_json_field(rpt.metric_stats)
    med_raw = _parse_json_field(rpt.medication_stats)
    event_raw = _parse_json_field(rpt.notable_events)

    return HealthReportResponse(
        id=rpt.id,
        member_id=rpt.member_id,
        period_type=rpt.period_type,
        period_start=rpt.period_start,
        period_end=rpt.period_end,
        status=rpt.status,
        metric_stats=[MetricStatItem(**s) for s in metric_raw] if metric_raw is not None else None,
        medication_stats=[MedicationStatItem(**s) for s in med_raw] if med_raw is not None else None,
        notable_events=[NotableEvent(**e) for e in event_raw] if event_raw is not None else None,
        llm_summary=rpt.llm_summary,
        created_at=rpt.created_at.isoformat(),
    )


# ── POST /{member_id}/generate ────────────────────────────────────────

@router.post(
    "/{member_id}/generate",
    response_model=HealthReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="生成健康周报或月报",
)
async def generate_report(
    body: ReportGenerateRequest,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: ReportService = Depends(_get_service),
):
    # 查询成员信息
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "成员不存在"})

    # 查询周期内健康记录
    from sqlalchemy import and_
    from datetime import datetime
    from zoneinfo import ZoneInfo

    period_start_dt = datetime(
        body.period_start.year, body.period_start.month, body.period_start.day,
        tzinfo=ZoneInfo("UTC")
    )
    period_end_dt = datetime(
        body.period_end.year, body.period_end.month, body.period_end.day,
        23, 59, 59, tzinfo=ZoneInfo("UTC")
    )

    records_result = await db.execute(
        select(HealthRecord).where(
            and_(
                HealthRecord.member_id == member_id,
                HealthRecord.measured_at >= period_start_dt,
                HealthRecord.measured_at <= period_end_dt,
            )
        )
    )
    records = records_result.scalars().all()

    # 查询活跃用药方案
    meds_result = await db.execute(
        select(Medication).where(
            and_(
                Medication.member_id == member_id,
                Medication.status == MedicationStatus.ACTIVE,
            )
        )
    )
    medications = meds_result.scalars().all()

    # 查询周期内依从性记录
    med_ids = [m.id for m in medications]
    adherence_logs = []
    if med_ids:
        logs_result = await db.execute(
            select(AdherenceLog).where(
                and_(
                    AdherenceLog.medication_id.in_(med_ids),
                    AdherenceLog.scheduled_at >= period_start_dt,
                    AdherenceLog.scheduled_at <= period_end_dt,
                )
            )
        )
        adherence_logs = logs_result.scalars().all()

    # 生成报告
    try:
        report_data = await svc.generate_report(
            member=member,
            records=records,
            medications=medications,
            adherence_logs=adherence_logs,
            period_type=body.period_type.value,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    except Exception as exc:
        log.error("报告生成失败", member_id=str(member_id), error=str(exc))
        report_data = {
            "metric_stats": None,
            "medication_stats": None,
            "notable_events": None,
            "llm_summary": None,
            "status": "failed",
        }

    report = HealthReport(
        member_id=member_id,
        period_type=body.period_type,
        period_start=body.period_start,
        period_end=body.period_end,
        status=ReportStatus(report_data["status"]),
        metric_stats=report_data["metric_stats"],
        medication_stats=report_data["medication_stats"],
        notable_events=report_data["notable_events"],
        llm_summary=report_data["llm_summary"],
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    log.info("健康报告已生成", report_id=str(report.id), period=body.period_type.value)
    return _build_response(report)


# ── GET /{member_id} ─────────────────────────────────────────────────

@router.get(
    "/{member_id}",
    response_model=List[HealthReportListItem],
    summary="列出健康报告历史",
)
async def list_reports(
    member_id: uuid.UUID = Depends(_member_id_param),
    period_type: Optional[ReportPeriod] = Query(None, description="按类型过滤 weekly/monthly"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HealthReport).where(HealthReport.member_id == member_id)
    if period_type:
        stmt = stmt.where(HealthReport.period_type == period_type)
    stmt = stmt.order_by(HealthReport.period_start.desc())

    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [
        HealthReportListItem(
            id=r.id,
            member_id=r.member_id,
            period_type=r.period_type,
            period_start=r.period_start,
            period_end=r.period_end,
            status=r.status,
            has_llm_summary=bool(r.llm_summary),
            created_at=r.created_at.isoformat(),
        )
        for r in reports
    ]


# ── GET /{member_id}/{report_id} ─────────────────────────────────────

@router.get(
    "/{member_id}/{report_id}",
    response_model=HealthReportResponse,
    summary="获取报告详情",
)
async def get_report(
    report_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(HealthReport, report_id)
    if report is None or report.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "报告不存在"})
    return _build_response(report)


# ── DELETE /{member_id}/{report_id} ──────────────────────────────────

@router.delete(
    "/{member_id}/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除报告",
)
async def delete_report(
    report_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(HealthReport, report_id)
    if report is None or report.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "报告不存在"})
    await db.delete(report)
    await db.commit()
