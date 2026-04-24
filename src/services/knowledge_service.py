"""
KnowledgeService — 健康知识库管理
职责：
  1. 将长文档切分为合适大小的 chunk
  2. 调用 OpenAI Embedding API 将 chunk 转为向量
  3. 将向量 + 元数据存入 Qdrant
  4. 向量相似度检索（供 RAG 使用）
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Optional

import structlog
import tiktoken
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

from src.core.config import settings
from src.core.qdrant import HEALTH_KNOWLEDGE_COLLECTION, EMBEDDING_DIM, ensure_collection

log = structlog.get_logger()

# ── 分块参数 ──────────────────────────────────────────────────────────
CHUNK_SIZE = 512        # 每块 token 数
CHUNK_OVERLAP = 64      # 相邻块重叠 token 数


def _get_tokenizer():
    """cl100k_base 适用于 text-embedding-3-small/large 和 GPT-4"""
    return tiktoken.get_encoding("cl100k_base")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    按 token 数量切分文本，相邻块有 overlap 个 token 的重叠，
    保证上下文不因分块边界丢失。
    """
    enc = _get_tokenizer()
    tokens = enc.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


class KnowledgeService:
    """健康知识库服务：摄入文档 + 语义检索"""

    def __init__(self, qdrant: AsyncQdrantClient, openai_client: Optional[AsyncOpenAI] = None):
        self._qdrant = qdrant
        self._openai = openai_client or AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """批量 Embedding，每批最多 100 条"""
        vectors: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            resp = await self._openai.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=batch,
            )
            vectors.extend([item.embedding for item in resp.data])
        return vectors

    async def ingest_document(
        self,
        content: str,
        source: str,
        category: str = "general",
        title: str = "",
    ) -> int:
        """
        将一篇文档摄入知识库。

        Args:
            content:  文档全文
            source:   来源标识（如 "丁香医生" / "默沙东手册"）
            category: 分类（如 "内科" / "儿科" / "药物"）
            title:    文章标题

        Returns:
            成功入库的 chunk 数量
        """
        await ensure_collection(self._qdrant)
        chunks = chunk_text(content)
        if not chunks:
            return 0

        vectors = await self._embed(chunks)

        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            # 用内容哈希作为稳定 ID，重复摄入不产生重复向量
            doc_hash = hashlib.md5(f"{source}:{title}:{idx}:{chunk[:50]}".encode()).hexdigest()
            point_id = str(uuid.UUID(doc_hash))
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "text": chunk,
                        "source": source,
                        "category": category,
                        "title": title,
                        "chunk_index": idx,
                    },
                )
            )

        await self._qdrant.upsert(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            points=points,
        )
        log.info("knowledge ingested", source=source, chunks=len(points))
        return len(points)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        语义检索最相关的知识片段。

        Args:
            query:    用户问题
            top_k:    返回 Top-K 个片段
            category: 可选，限定知识分类

        Returns:
            list of {"text", "source", "title", "score"}
        """
        query_vector = (await self._embed([query]))[0]

        search_filter = None
        if category:
            search_filter = Filter(
                must=[FieldCondition(
                    key="category",
                    match=MatchValue(value=category),
                )]
            )

        results = await self._qdrant.search(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            query_vector=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
        )

        return [
            {
                "text": r.payload["text"],
                "source": r.payload.get("source", ""),
                "title": r.payload.get("title", ""),
                "score": round(r.score, 4),
            }
            for r in results
        ]

    async def delete_by_source(self, source: str) -> None:
        """删除指定来源的所有向量（用于知识库更新）"""
        from qdrant_client.models import FilterSelector
        await self._qdrant.delete(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                )
            ),
        )
        log.info("knowledge deleted", source=source)

    async def collection_stats(self) -> dict:
        """返回知识库统计信息"""
        try:
            info = await self._qdrant.get_collection(HEALTH_KNOWLEDGE_COLLECTION)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception:
            return {"vectors_count": 0, "points_count": 0, "status": "not_initialized"}
