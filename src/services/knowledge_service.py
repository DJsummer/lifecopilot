"""
KnowledgeService — 健康知识库管理（v2）
==========================================
新增能力：
  1. 表格感知分块（Markdown 表格整体保留，不按 token 硬切）
  2. 通过 EmbeddingService 向量化（支持本地 bge-m3 或 OpenAI API，含 Redis 缓存）
  3. CrossEncoder Reranker 重排（可选，USE_RERANKER=true 时启用）
  4. Redis 查询结果缓存（QUERY_CACHE_TTL 秒）
  5. 三类知识分区（disease / red_flag / triage）供 Agentic RAG 路由使用

向后兼容：
  - chunk_text(text, chunk_size, overlap) 函数签名不变（测试依赖）
  - KnowledgeService 所有公共方法签名不变
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

from src.core.config import settings
from src.core.qdrant import HEALTH_KNOWLEDGE_COLLECTION, EMBEDDING_DIM, ensure_collection
from src.services import embedding_service as emb

log = logging.getLogger(__name__)

# ── 分块默认参数 ──────────────────────────────────────────────────────
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# ── Reranker 延迟加载 ─────────────────────────────────────────────────
_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None and settings.USE_RERANKER:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(
                settings.RERANKER_MODEL,
                cache_folder=settings.HF_CACHE_DIR,
            )
            log.info("Reranker loaded: %s", settings.RERANKER_MODEL)
        except Exception as e:
            log.warning("Reranker unavailable, skip rerank: %s", e)
    return _reranker


# ── Redis 查询缓存 ────────────────────────────────────────────────────
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
        _redis_client.ping()
    except Exception:
        _redis_client = None
    return _redis_client


def _query_cache_key(query: str, category: Optional[str], top_k: int) -> str:
    raw = f"{query}|{category}|{top_k}"
    return "qcache:" + hashlib.md5(raw.encode()).hexdigest()


def _read_query_cache(key: str) -> Optional[list]:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _write_query_cache(key: str, results: list) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, settings.QUERY_CACHE_TTL, json.dumps(results))
    except Exception:
        pass


# ── Token 计数 ────────────────────────────────────────────────────────
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_enc.encode(text))

    def _decode_tokens(tokens) -> str:
        return _enc.decode(tokens)

    def _encode_tokens(text: str) -> list:
        return _enc.encode(text)

except ImportError:
    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        return len(text)

    def _decode_tokens(tokens) -> str:  # type: ignore[misc]
        return "".join(tokens)

    def _encode_tokens(text: str) -> list:  # type: ignore[misc]
        return list(text)


# ── 原始 chunk_text（保持向后兼容，供测试和外部脚本使用）─────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    按 token 数量切分文本（纯 token 切分，无表格感知）。
    保留此函数以维持测试兼容性；ingest_document 内部使用更高级的实现。
    """
    tokens = _encode_tokens(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(_decode_tokens(tokens[start:end]))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


# ── 表格感知分块（用于实际 ingest，参考 /AI/rag/services/chunker.py）────

def _chunk_text_advanced(
    text: str,
    source: str = "",
    title: str = "",
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    表格感知分块：
    - Markdown 表格（含 | 分隔符的行）整体保留，不二次切分
    - 普通段落按 token 切分，支持 overlap
    - 在每个 chunk 前加 "[title/source]" 前缀（提升检索质量）
    """
    raw_text = text.strip()
    if not raw_text:
        return []

    header = f"[{title or source}]\n" if (title or source) else ""
    header_tokens = _count_tokens(header)
    effective_size = chunk_size - header_tokens

    # 按段落（双换行）切分，表格行整体保留
    paragraphs: list[str] = []
    for block in raw_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # 含 | 的块视为 Markdown 表格，整块保留
        if " | " in block or block.startswith("|"):
            paragraphs.append(block)
        else:
            for line in block.split("\n"):
                line = line.strip()
                if line:
                    paragraphs.append(line)

    chunks: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def _flush(buf: list[str]) -> str:
        return header + "\n".join(buf)

    for para in paragraphs:
        para_tokens = _count_tokens(para)

        # 超大段落（含整个表格）单独成块
        if para_tokens >= effective_size:
            if buffer:
                chunks.append(_flush(buffer))
            chunks.append(header + para)
            buffer, buffer_tokens = [], 0
            continue

        if buffer_tokens + para_tokens > effective_size and buffer:
            chunks.append(_flush(buffer))
            # overlap：保留 buffer 末尾若干段落
            overlap_buf: list[str] = []
            overlap_tokens = 0
            for item in reversed(buffer):
                t = _count_tokens(item)
                if overlap_tokens + t > overlap:
                    break
                overlap_buf.insert(0, item)
                overlap_tokens += t
            buffer, buffer_tokens = overlap_buf, overlap_tokens

        buffer.append(para)
        buffer_tokens += para_tokens

    if buffer:
        chunks.append(_flush(buffer))

    return chunks


# ── KnowledgeService ─────────────────────────────────────────────────

class KnowledgeService:
    """健康知识库服务：摄入文档 + 语义检索 + Rerank + 查询缓存"""

    def __init__(self, qdrant: AsyncQdrantClient):
        self._qdrant = qdrant

    # ── Rerank（在线程池运行，因为 CrossEncoder 是同步的）─────────────────

    def _rerank_sync(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        reranker = _get_reranker()
        if reranker is None:
            return hits[:top_k]
        pairs = [(query, h["text"]) for h in hits]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)
        return [h for _, h in ranked[:top_k]]

    # ── 文档摄入 ─────────────────────────────────────────────────────

    async def ingest_document(
        self,
        content: str,
        source: str,
        category: str = "disease",
        title: str = "",
    ) -> int:
        """
        将一篇文档摄入知识库（表格感知分块 + 缓存 embedding + 幂等 upsert）。

        category 推荐值：
          - "disease"   通用疾病科普（默认）
          - "red_flag"  紧急症状/危险症状（触发则直接提示就医）
          - "triage"    分诊导诊（判断挂哪个科室）
          - "drug"      药物说明
          - "general"   其他
        """
        await ensure_collection(self._qdrant)

        chunks = _chunk_text_advanced(content, source=source, title=title)
        if not chunks:
            return 0

        vectors = await emb.get_embeddings(chunks)

        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
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
        log.info("knowledge ingested source=%s category=%s chunks=%d", source, category, len(points))
        return len(points)

    # ── 语义检索 ─────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        语义检索最相关的知识片段（含 Redis 缓存 + 可选 CrossEncoder rerank）。

        Returns:
            list of {"text", "source", "title", "category", "score"}
        """
        # 查询缓存
        cache_key = _query_cache_key(query, category, top_k)
        cached = _read_query_cache(cache_key)
        if cached is not None:
            return cached

        # 向量化
        query_vector = await emb.get_embedding(query)

        search_filter = None
        if category:
            search_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )

        fetch_k = top_k * 2 if settings.USE_RERANKER else top_k
        raw_hits = await self._qdrant.search(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            query_vector=query_vector,
            limit=fetch_k,
            query_filter=search_filter,
            with_payload=True,
            score_threshold=0.3,
        )

        if not raw_hits:
            return []

        hits = [
            {
                "text": h.payload.get("text", ""),
                "source": h.payload.get("source", ""),
                "title": h.payload.get("title", ""),
                "category": h.payload.get("category", "general"),
                "score": h.score,
            }
            for h in raw_hits
        ]

        # Rerank
        if settings.USE_RERANKER and len(hits) > top_k:
            hits = await asyncio.to_thread(self._rerank_sync, query, hits, top_k)
        else:
            hits = hits[:top_k]

        _write_query_cache(cache_key, hits)
        return hits

    # ── 并行多类别检索（供 ChatService Agentic 模式）─────────────────

    async def search_multi_category(
        self,
        query: str,
        categories: list[str],
        top_k: int = 4,
    ) -> dict[str, list[dict]]:
        """并行搜索多个 category，返回 {category: [chunks]}"""
        tasks = [self.search(query, top_k=top_k, category=cat) for cat in categories]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, list[dict]] = {}
        for cat, res in zip(categories, results_list):
            out[cat] = res if isinstance(res, list) else []
        return out

    # ── 按来源删除 ────────────────────────────────────────────────────

    async def delete_by_source(self, source: str) -> int:
        """按来源标识批量删除向量"""
        from qdrant_client.models import FilterSelector
        await self._qdrant.delete(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                )
            ),
        )
        log.info("knowledge deleted source=%s", source)
        return 0

    # ── 统计信息 ──────────────────────────────────────────────────────

    async def collection_stats(self) -> dict:
        try:
            info = await self._qdrant.get_collection(HEALTH_KNOWLEDGE_COLLECTION)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value if hasattr(info.status, "value") else str(info.status),
            }
        except Exception as e:
            return {"vectors_count": None, "points_count": None, "status": f"error: {e}"}
