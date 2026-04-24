"""RAG 问答 + 知识库管理路由 — /api/v1/chat（v2）

v2 升级：
  - 会话默认按 member_id 隔离（每人独立记忆）
  - chat/stream 端点在调用前从 DB 查询成员健康档案并注入 member_context
  - 新增 DELETE /sessions/me 清除当前成员的对话历史
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.chat import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    KnowledgeStatsResponse,
    SourceReference,
)
from src.core.database import get_db
from src.core.deps import get_current_admin, get_current_member
from src.core.qdrant import get_qdrant_client
from src.models.health import HealthRecord, MetricType
from src.models.medication import Medication, MedicationStatus
from src.models.member import Member
from src.services.chat_service import (
    ChatService,
    ChatSession,
    clear_member_session,
    get_or_create_member_session,
)
from src.services.knowledge_service import KnowledgeService

log = structlog.get_logger()
router = APIRouter()


# ── 成员健康档案构建（从 DB 查询，注入 member_context）─────────────────

async def _build_member_context(member: Member, db: AsyncSession) -> dict:
    """
    从数据库查询成员的基本信息 + 最新健康指标 + 当前用药，
    构建供 ChatService 使用的 member_context 字典。
    """
    ctx: dict = {
        "nickname": member.nickname,
        "role": member.role.value if hasattr(member.role, "value") else member.role,
    }
    if member.gender:
        ctx["gender"] = member.gender.value if hasattr(member.gender, "value") else member.gender

    # 计算年龄
    if member.birth_date:
        today = date.today()
        age = today.year - member.birth_date.year
        if today < member.birth_date.replace(year=today.year):
            age -= 1
        ctx["age"] = age

    # 最新关键健康指标
    key_metrics = [
        MetricType.BLOOD_PRESSURE_SYS,
        MetricType.BLOOD_PRESSURE_DIA,
        MetricType.BLOOD_GLUCOSE,
        MetricType.WEIGHT,
        MetricType.HEART_RATE,
    ]
    for metric in key_metrics:
        stmt = (
            select(HealthRecord.value, HealthRecord.unit)
            .where(
                HealthRecord.member_id == member.id,
                HealthRecord.metric_type == metric,
            )
            .order_by(desc(HealthRecord.measured_at))
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.first()
        if row:
            ctx[metric.value] = f"{row.value} {row.unit}"

    # 当前用药清单（最多 5 种）
    stmt = (
        select(Medication.name, Medication.dosage, Medication.frequency)
        .where(
            Medication.member_id == member.id,
            Medication.status == MedicationStatus.ACTIVE,
        )
        .limit(5)
    )
    result = await db.execute(stmt)
    meds = result.fetchall()
    if meds:
        ctx["medications"] = "、".join(
            f"{m.name} {m.dosage or ''} {m.frequency or ''}".strip()
            for m in meds
        )

    # 去除空值
    return {k: v for k, v in ctx.items() if v is not None and v != ""}


# ── Service 工厂 ──────────────────────────────────────────────────────

def _get_services() -> tuple[KnowledgeService, ChatService]:
    client = get_qdrant_client()
    knowledge_svc = KnowledgeService(client)
    chat_svc = ChatService(knowledge_svc)
    return knowledge_svc, chat_svc


# ── 问答（非流式） ────────────────────────────────────────────────────
@router.post(
    "/",
    response_model=ChatResponse,
    summary="健康问答（同步，完整返回）",
)
async def chat(
    body: ChatRequest,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    # 会话：优先使用请求指定的 session_id，否则按 member_id 隔离
    target_member_id = str(body.member_id or current.id)
    explicit_session_id = body.session_id

    if explicit_session_id:
        # 兼容旧客户端传 session_id 的场景
        from src.services.chat_service import _member_sessions, ChatSession as _CS
        if explicit_session_id not in _member_sessions:
            _member_sessions[explicit_session_id] = _CS()
        session = _member_sessions[explicit_session_id]
        session_id = explicit_session_id
    else:
        session = get_or_create_member_session(target_member_id)
        session_id = target_member_id

    _, chat_svc = _get_services()
    member_context = await _build_member_context(current, db)

    try:
        answer = await chat_svc.chat(
            question=body.question,
            session=session,
            member_context=member_context,
            top_k=body.top_k,
        )
    except Exception as e:
        log.error("chat error", error=str(e))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LLM_UNAVAILABLE", "message": "AI 服务暂时不可用，请稍后重试"},
        )

    # 获取本次检索的 sources
    knowledge_svc, _ = _get_services()
    try:
        chunks = await knowledge_svc.search(body.question, top_k=body.top_k)
        sources = [
            SourceReference(source=c["source"], title=c["title"], score=c["score"])
            for c in chunks if c["source"]
        ]
    except Exception:
        sources = []

    return ChatResponse(session_id=session_id, answer=answer, sources=sources)


# ── 问答（流式 SSE） ──────────────────────────────────────────────────
@router.post(
    "/stream",
    summary="健康问答（流式 SSE，逐字输出）",
    response_class=StreamingResponse,
)
async def chat_stream(
    body: ChatRequest,
    current: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    target_member_id = str(body.member_id or current.id)
    explicit_session_id = body.session_id

    if explicit_session_id:
        from src.services.chat_service import _member_sessions, ChatSession as _CS
        if explicit_session_id not in _member_sessions:
            _member_sessions[explicit_session_id] = _CS()
        session = _member_sessions[explicit_session_id]
        session_id = explicit_session_id
    else:
        session = get_or_create_member_session(target_member_id)
        session_id = target_member_id

    _, chat_svc = _get_services()
    member_context = await _build_member_context(current, db)

    async def event_generator():
        yield f"data: {json.dumps({'session_id': session_id, 'type': 'start'}, ensure_ascii=False)}\n\n"
        try:
            async for delta in chat_svc.stream_chat(
                question=body.question,
                session=session,
                member_context=member_context,
                top_k=body.top_k,
            ):
                payload = json.dumps({"delta": delta, "type": "delta"}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as e:
            log.error("stream chat error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': 'AI服务暂时不可用'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 会话管理 ──────────────────────────────────────────────────────────

@router.delete(
    "/sessions/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="清空当前成员的对话历史",
)
async def clear_my_session(current: Member = Depends(get_current_member)):
    """清除当前登录成员的专属对话记忆"""
    clear_member_session(str(current.id))


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="清空指定 session_id 的对话历史（兼容旧客户端）",
)
async def clear_session(
    session_id: str,
    current: Member = Depends(get_current_member),
):
    from src.services.chat_service import _member_sessions
    _member_sessions.pop(session_id, None)


# ── 知识库管理（仅 admin） ────────────────────────────────────────────

@router.post(
    "/knowledge",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="摄入健康知识文档（仅 admin）",
)
async def ingest_knowledge(
    body: IngestRequest,
    _: Member = Depends(get_current_admin),
):
    knowledge_svc, _ = _get_services()
    try:
        chunks = await knowledge_svc.ingest_document(
            content=body.content,
            source=body.source,
            title=body.title,
            category=body.category,
        )
    except Exception as e:
        log.error("ingest error", error=str(e))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "QDRANT_UNAVAILABLE", "message": str(e)},
        )
    return IngestResponse(chunks_created=chunks, source=body.source, title=body.title)


@router.delete(
    "/knowledge/{source}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除指定来源的所有知识（仅 admin）",
)
async def delete_knowledge(source: str, _: Member = Depends(get_current_admin)):
    knowledge_svc, _ = _get_services()
    await knowledge_svc.delete_by_source(source)


@router.get(
    "/knowledge/stats",
    response_model=KnowledgeStatsResponse,
    summary="知识库统计信息（仅 admin）",
)
async def knowledge_stats(_: Member = Depends(get_current_admin)):
    knowledge_svc, _ = _get_services()
    stats = await knowledge_svc.collection_stats()
    return KnowledgeStatsResponse(**stats)
