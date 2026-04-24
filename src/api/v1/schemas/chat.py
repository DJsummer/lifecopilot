from __future__ import annotations
"""Pydantic Schema：RAG 问答 + 知识库管理"""
from typing import Optional, List
import uuid

from pydantic import BaseModel, Field


# ── 问答 ──────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: Optional[str] = Field(default=None, description="会话 ID（多轮对话用，首次不传）")
    member_id: Optional[uuid.UUID] = Field(default=None, description="成员 ID（附加健康背景）")
    top_k: int = Field(default=4, ge=1, le=10, description="RAG 检索 Top-K 片段数")


class SourceReference(BaseModel):
    source: str
    title: str
    score: float


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: List[SourceReference] = []


# ── 知识库管理（仅内部 / admin 使用）────────────────────────────────
class IngestRequest(BaseModel):
    content: str = Field(..., min_length=10, description="文档全文")
    source: str = Field(..., min_length=1, max_length=100, description="来源（如：丁香医生）")
    title: str = Field(default="", max_length=200, description="文章标题")
    category: str = Field(default="general", max_length=50, description="分类")


class IngestResponse(BaseModel):
    chunks_created: int
    source: str
    title: str


class KnowledgeStatsResponse(BaseModel):
    vectors_count: Optional[int]
    points_count: Optional[int]
    status: str
