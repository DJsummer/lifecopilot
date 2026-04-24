"""心理健康筛查路由 — /api/v1/mental-health (T016)"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.mental_health import (
    AssessmentCreate,
    EmotionDiaryCreate,
    GAD7QuestionsResponse,
    GAD7_QUESTIONS,
    MentalHealthLogListItem,
    MentalHealthLogResponse,
    PHQ9QuestionsResponse,
    PHQ9_QUESTIONS,
)
from src.core.database import get_db
from src.core.deps import get_current_member, require_same_family
from src.models.mental_health import EntryType, MentalHealthLog, RiskLevel
from src.models.member import Member
from src.services.mental_health_service import (
    MentalHealthService,
    combine_risk,
    get_resources,
    score_gad7,
    score_phq9,
)

log = structlog.get_logger()
router = APIRouter()

_SERVICE: Optional[MentalHealthService] = None


def _get_service() -> MentalHealthService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = MentalHealthService()
    return _SERVICE


def _member_id_param(
    member_id: uuid.UUID,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    require_same_family(member_id, current)
    return member_id


def _parse_json_list(raw: Optional[str]) -> Optional[List]:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _build_response(r: MentalHealthLog) -> MentalHealthLogResponse:
    return MentalHealthLogResponse(
        id=r.id,
        member_id=r.member_id,
        entry_type=r.entry_type,
        emotion_text=r.emotion_text,
        emotion_tags=_parse_json_list(r.emotion_tags),
        mood_score=r.mood_score,
        nlp_analysis=r.nlp_analysis,
        phq9_answers=_parse_json_list(r.phq9_answers),
        phq9_score=r.phq9_score,
        gad7_answers=_parse_json_list(r.gad7_answers),
        gad7_score=r.gad7_score,
        risk_level=r.risk_level,
        resources=_parse_json_list(r.resources),
        occurred_at=r.occurred_at,
        created_at=r.created_at,
    )


# ── GET /phq9/questions — PHQ-9 题目 ─────────────────────────────────

@router.get(
    "/phq9/questions",
    response_model=PHQ9QuestionsResponse,
    summary="获取 PHQ-9 抑郁自评量表题目",
)
async def get_phq9_questions():
    return PHQ9QuestionsResponse(questions=PHQ9_QUESTIONS)


# ── GET /gad7/questions — GAD-7 题目 ─────────────────────────────────

@router.get(
    "/gad7/questions",
    response_model=GAD7QuestionsResponse,
    summary="获取 GAD-7 广泛性焦虑量表题目",
)
async def get_gad7_questions():
    return GAD7QuestionsResponse(questions=GAD7_QUESTIONS)


# ── POST /{member_id}/diary — 情绪日记 ───────────────────────────────

@router.post(
    "/{member_id}/diary",
    response_model=MentalHealthLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="记录情绪日记并进行 NLP 情绪分析",
)
async def create_emotion_diary(
    body: EmotionDiaryCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: MentalHealthService = Depends(_get_service),
):
    occurred_at = body.occurred_at or datetime.now(tz=timezone.utc)

    # LLM 情绪分析（失败时静默降级）
    nlp = await svc.analyze_emotion(body.emotion_text, body.emotion_tags)

    # 合并用户标注 + LLM 检测的情绪标签（去重）
    all_tags = list(dict.fromkeys(
        (body.emotion_tags or []) + (nlp.get("detected_tags") or [])
    ))

    risk_level = nlp.get("risk_hint", "low")
    resources = get_resources(risk_level)

    record = MentalHealthLog(
        member_id=member_id,
        entry_type=EntryType.DIARY,
        emotion_text=body.emotion_text,
        emotion_tags=json.dumps(all_tags, ensure_ascii=False) if all_tags else None,
        mood_score=nlp.get("mood_score"),
        nlp_analysis=nlp.get("nlp_analysis"),
        risk_level=risk_level,
        resources=json.dumps(resources, ensure_ascii=False),
        occurred_at=occurred_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    log.info(
        "情绪日记已记录",
        log_id=str(record.id),
        risk=risk_level,
        mood=record.mood_score,
    )
    return _build_response(record)


# ── POST /{member_id}/assess — 量表评估 ──────────────────────────────

@router.post(
    "/{member_id}/assess",
    response_model=MentalHealthLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交 PHQ-9 / GAD-7 量表答案（可附带情绪日记）",
)
async def create_assessment(
    body: AssessmentCreate,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
    svc: MentalHealthService = Depends(_get_service),
):
    if body.phq9_answers is None and body.gad7_answers is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="phq9_answers 和 gad7_answers 至少需要提交一项",
        )

    occurred_at = body.occurred_at or datetime.now(tz=timezone.utc)

    risk_levels: List[str] = []

    # PHQ-9 评分（纯规则）
    phq9_score: Optional[int] = None
    phq9_risk: Optional[str] = None
    if body.phq9_answers is not None:
        phq9_score, phq9_risk = score_phq9(body.phq9_answers)
        risk_levels.append(phq9_risk)

    # GAD-7 评分（纯规则）
    gad7_score: Optional[int] = None
    gad7_risk: Optional[str] = None
    if body.gad7_answers is not None:
        gad7_score, gad7_risk = score_gad7(body.gad7_answers)
        risk_levels.append(gad7_risk)

    # 可选情绪日记 NLP
    nlp_analysis: Optional[str] = None
    mood_score: Optional[int] = None
    all_tags: List[str] = list(body.emotion_tags or [])

    if body.emotion_text:
        nlp = await svc.analyze_emotion(body.emotion_text, body.emotion_tags)
        nlp_analysis = nlp.get("nlp_analysis")
        mood_score = nlp.get("mood_score")
        nlp_risk = nlp.get("risk_hint", "low")
        risk_levels.append(nlp_risk)
        extra_tags = nlp.get("detected_tags") or []
        all_tags = list(dict.fromkeys(all_tags + extra_tags))

    # 决定 entry_type
    has_diary = bool(body.emotion_text)
    has_phq9 = body.phq9_answers is not None
    has_gad7 = body.gad7_answers is not None
    if has_diary and (has_phq9 or has_gad7):
        entry_type = EntryType.COMBINED
    elif has_phq9 and has_gad7:
        entry_type = EntryType.COMBINED
    elif has_phq9:
        entry_type = EntryType.PHQ9
    else:
        entry_type = EntryType.GAD7

    risk_level = combine_risk(risk_levels) if risk_levels else "low"
    resources = get_resources(risk_level)

    record = MentalHealthLog(
        member_id=member_id,
        entry_type=entry_type,
        emotion_text=body.emotion_text,
        emotion_tags=json.dumps(all_tags, ensure_ascii=False) if all_tags else None,
        mood_score=mood_score,
        nlp_analysis=nlp_analysis,
        phq9_answers=json.dumps(body.phq9_answers) if body.phq9_answers is not None else None,
        phq9_score=phq9_score,
        gad7_answers=json.dumps(body.gad7_answers) if body.gad7_answers is not None else None,
        gad7_score=gad7_score,
        risk_level=risk_level,
        resources=json.dumps(resources, ensure_ascii=False),
        occurred_at=occurred_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    log.info(
        "心理健康量表评估已记录",
        log_id=str(record.id),
        phq9=phq9_score,
        gad7=gad7_score,
        risk=risk_level,
    )
    return _build_response(record)


# ── GET /{member_id} — 列表 ──────────────────────────────────────────

@router.get(
    "/{member_id}",
    response_model=List[MentalHealthLogListItem],
    summary="心理健康记录列表",
)
async def list_mental_health_logs(
    member_id: uuid.UUID = Depends(_member_id_param),
    risk_level: Optional[str] = Query(None, description="按风险等级过滤：low/moderate/high/crisis"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(MentalHealthLog)
        .where(MentalHealthLog.member_id == member_id)
        .order_by(MentalHealthLog.occurred_at.desc())
    )
    if risk_level:
        stmt = stmt.where(MentalHealthLog.risk_level == risk_level)

    rows = (await db.execute(stmt)).scalars().all()

    result = []
    for r in rows:
        result.append(MentalHealthLogListItem(
            id=r.id,
            entry_type=r.entry_type,
            risk_level=r.risk_level,
            mood_score=r.mood_score,
            phq9_score=r.phq9_score,
            gad7_score=r.gad7_score,
            emotion_tags=_parse_json_list(r.emotion_tags),
            occurred_at=r.occurred_at,
            created_at=r.created_at,
        ))
    return result


# ── GET /{member_id}/{log_id} — 详情 ────────────────────────────────

@router.get(
    "/{member_id}/{log_id}",
    response_model=MentalHealthLogResponse,
    summary="心理健康记录详情",
)
async def get_mental_health_log(
    log_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(MentalHealthLog, log_id)
    if record is None or record.member_id != member_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    return _build_response(record)


# ── DELETE /{member_id}/{log_id} — 删除 ─────────────────────────────

@router.delete(
    "/{member_id}/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除心理健康记录",
)
async def delete_mental_health_log(
    log_id: uuid.UUID,
    member_id: uuid.UUID = Depends(_member_id_param),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(MentalHealthLog, log_id)
    if record is None or record.member_id != member_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    await db.delete(record)
    await db.commit()
