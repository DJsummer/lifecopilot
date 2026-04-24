"""RAG 问答 + 知识库管理路由 — /api/v1/chat"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
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
from src.models.member import Member
from src.services.chat_service import ChatService, ChatSession
from src.services.knowledge_service import KnowledgeService

log = structlog.get_logger()
router = APIRouter()

# ── 内存会话存储（生产环境应改用 Redis）────────────────────────────────
# key: session_id (str), value: ChatSession
_sessions: dict[str, ChatSession] = {}

MAX_SESSIONS = 10000  # 防止内存无限增长


def _get_or_create_session(session_id: Optional[str]) -> tuple[str, ChatSession]:
    """获取或新建会话，返回 (session_id, session)"""
    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]
    new_id = str(uuid.uuid4())
    session = ChatSession()
    if len(_sessions) >= MAX_SESSIONS:
        # 简单 LRU：删掉第一个
        oldest = next(iter(_sessions))
        del _sessions[oldest]
    _sessions[new_id] = session
    return new_id, session


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
    session_id, session = _get_or_create_session(body.session_id)
    _, chat_svc = _get_services()

    # 可选：附加成员健康背景（此处简化，实际可查询最新健康摘要）
    member_context = None
    if body.member_id:
        member_context = {"member_id": str(body.member_id)}

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

    # 获取最近一次检索的来源（简化：重新检索一次）
    knowledge_svc, _ = _get_services()
    try:
        chunks = await knowledge_svc.search(body.question, top_k=body.top_k)
        sources = [
            SourceReference(source=c["source"], title=c["title"], score=c["score"])
            for c in chunks
            if c["source"]
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
):
    session_id, session = _get_or_create_session(body.session_id)
    _, chat_svc = _get_services()

    member_context = None
    if body.member_id:
        member_context = {"member_id": str(body.member_id)}

    async def event_generator():
        # 首先发送 session_id
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


# ── 清空会话 ──────────────────────────────────────────────────────────
@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="清空指定会话的对话历史",
)
async def clear_session(
    session_id: str,
    current: Member = Depends(get_current_member),
):
    _sessions.pop(session_id, None)


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
            detail={"code": "QDRANT_UNAVAILABLE", "message": "向量数据库暂时不可用"},
        )
    return IngestResponse(chunks_created=chunks, source=body.source, title=body.title)


@router.delete(
    "/knowledge/{source}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除指定来源的所有知识片段（仅 admin）",
)
async def delete_knowledge(
    source: str,
    _: Member = Depends(get_current_admin),
):
    knowledge_svc, _ = _get_services()
    try:
        await knowledge_svc.delete_by_source(source)
    except Exception as e:
        log.error("delete knowledge error", error=str(e))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "QDRANT_UNAVAILABLE", "message": "向量数据库暂时不可用"},
        )


@router.get(
    "/knowledge/stats",
    response_model=KnowledgeStatsResponse,
    summary="查看知识库统计（仅 admin）",
)
async def knowledge_stats(
    _: Member = Depends(get_current_admin),
):
    knowledge_svc, _ = _get_services()
    try:
        stats = await knowledge_svc.collection_stats()
    except Exception:
        stats = {"vectors_count": 0, "points_count": 0, "status": "unavailable"}
    return KnowledgeStatsResponse(**stats)
