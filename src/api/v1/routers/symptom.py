"""症状日记 NLP 分析路由 — /api/v1/symptoms (T011)"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.symptom import (
    SymptomItem,
    SymptomLogCreate,
    SymptomLogListItem,
    SymptomLogResponse,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.health import SymptomLog, VisitAdviceLevel
from src.models.member import Member
from src.services.symptom_service import SymptomService

log = structlog.get_logger()
router = APIRouter()

_SERVICE: Optional[SymptomService] = None


def _get_service() -> SymptomService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SymptomService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _parse_symptoms(raw: Optional[str]) -> Optional[List[SymptomItem]]:
    if not raw:
        return None
    try:
        items = json.loads(raw)
        return [SymptomItem(**s) for s in items]
    except Exception:
        return None


def _build_response(sl: SymptomLog) -> SymptomLogResponse:
    return SymptomLogResponse(
        id=sl.id,
        member_id=sl.member_id,
        raw_text=sl.raw_text,
        occurred_at=sl.occurred_at.isoformat(),
        structured_symptoms=_parse_symptoms(sl.structured_symptoms),
        severity_score=sl.severity_score,
        advice_level=sl.advice_level,
        llm_summary=sl.llm_summary,
        created_at=sl.created_at.isoformat(),
    )


# ── POST /{member_id} — 记录并分析症状 ───────────────────────────────

@router.post(
    "/{member_id}",
    response_model=SymptomLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="记录症状日记并进行 NLP 分析",
)
async def create_symptom_log(
    body: SymptomLogCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: SymptomService = Depends(_get_service),
):
    occurred_at = body.occurred_at or datetime.now(tz=timezone.utc)

    # LLM 分析（失败时静默降级）
    analysis = await svc.analyze(body.raw_text)

    sl = SymptomLog(
        member_id=member_id,
        raw_text=body.raw_text,
        occurred_at=occurred_at,
        structured_symptoms=analysis["structured_symptoms"],
        severity_score=analysis["severity_score"],
        advice_level=VisitAdviceLevel(analysis["advice_level"]) if analysis["advice_level"] else None,
        llm_summary=analysis["llm_summary"],
    )
    db.add(sl)
    await db.commit()
    await db.refresh(sl)

    log.info(
        "症状日记已记录",
        log_id=str(sl.id),
        severity=sl.severity_score,
        advice=sl.advice_level,
    )
    return _build_response(sl)


# ── GET /{member_id} — 列表 ──────────────────────────────────────────

@router.get(
    "/{member_id}",
    response_model=List[SymptomLogListItem],
    summary="症状日记列表",
)
async def list_symptom_logs(
    member_id: uuid.UUID = Depends(_member_id_param),
    advice_level: Optional[VisitAdviceLevel] = Query(None, description="按就医建议等级过滤"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SymptomLog)
        .where(SymptomLog.member_id == member_id)
        .order_by(SymptomLog.occurred_at.desc())
    )
    if advice_level:
        stmt = stmt.where(SymptomLog.advice_level == advice_level)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        SymptomLogListItem(
            id=sl.id,
            member_id=sl.member_id,
            raw_text=sl.raw_text,
            occurred_at=sl.occurred_at.isoformat(),
            severity_score=sl.severity_score,
            advice_level=sl.advice_level,
            has_analysis=bool(sl.structured_symptoms),
            created_at=sl.created_at.isoformat(),
        )
        for sl in logs
    ]


# ── GET /{member_id}/{log_id} — 详情 ─────────────────────────────────

@router.get(
    "/{member_id}/{log_id}",
    response_model=SymptomLogResponse,
    summary="症状日记详情",
)
async def get_symptom_log(
    log_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    sl = await db.get(SymptomLog, log_id)
    if sl is None or sl.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "记录不存在"})
    return _build_response(sl)


# ── DELETE /{member_id}/{log_id} — 删除 ──────────────────────────────

@router.delete(
    "/{member_id}/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除症状日记",
)
async def delete_symptom_log(
    log_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    sl = await db.get(SymptomLog, log_id)
    if sl is None or sl.member_id != member_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "记录不存在"})
    await db.delete(sl)
    await db.commit()
