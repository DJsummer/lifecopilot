"""
EmbeddingService — 文本向量化服务
====================================
两种模式（通过 settings.USE_LOCAL_EMBEDDING 切换）：
  - False（默认）：调用 OpenAI Embedding API（text-embedding-3-small）
  - True：本地加载 BAAI/bge-m3，CPU/GPU 推理（无网络依赖）

公共特性（两种模式均支持）：
  - Redis 缓存（TTL 7 天），避免重复调用/推理
  - 单条 + 批量接口
  - asyncio 友好（同步推理通过 asyncio.to_thread 在线程池运行）
  - Redis/模型不可用时优雅降级（不抛出异常中断主流程）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── 延迟初始化（避免 import 阶段占用资源）─────────────────────────────
_redis_client = None
_local_model = None  # sentence_transformers.SentenceTransformer
_openai_client = None


def _get_redis():
    """获取 Redis 同步客户端（最佳努力，失败则返回 None）"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        from src.core.config import settings
        _redis_client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        _redis_client.ping()
    except Exception as e:
        log.debug("Redis unavailable for embedding cache: %s", e)
        _redis_client = None
    return _redis_client


def _get_local_model():
    """延迟加载本地 SentenceTransformer 模型"""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        from src.core.config import settings
        log.info("Loading local embedding model: %s  device=%s", settings.LOCAL_EMBEDDING_MODEL, settings.EMBEDDING_DEVICE)
        _local_model = SentenceTransformer(
            settings.LOCAL_EMBEDDING_MODEL,
            device=settings.EMBEDDING_DEVICE,
            cache_folder=settings.HF_CACHE_DIR,
        )
        log.info("Local embedding model loaded, dim=%d", _local_model.get_sentence_embedding_dimension())
    return _local_model


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        from src.core.config import settings
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _openai_client


# ── 缓存工具 ─────────────────────────────────────────────────────────

def _cache_key(text: str, model_tag: str) -> str:
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"embed:{model_tag.replace('/', '_')}:{digest}"


def _read_cache(key: str) -> Optional[list]:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _write_cache(key: str, vec: list, ttl: int) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(vec))
    except Exception:
        pass


# ── 本地批量推理（同步，在线程池运行）──────────────────────────────────

def _local_embed_batch_sync(texts: list[str]) -> list[list[float]]:
    from src.core.config import settings
    model = _get_local_model()
    vecs = model.encode(
        texts,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


# ── 公共异步接口 ─────────────────────────────────────────────────────

async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    主接口：给定文本列表，返回等长向量列表。
    自动使用缓存（命中则跳过推理）。
    """
    from src.core.config import settings

    model_tag = settings.LOCAL_EMBEDDING_MODEL if settings.USE_LOCAL_EMBEDDING else settings.EMBEDDING_MODEL
    ttl = settings.EMBEDDING_CACHE_TTL

    results: list[Optional[list]] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    # ── 查缓存 ──
    for i, text in enumerate(texts):
        key = _cache_key(text, model_tag)
        cached = _read_cache(key)
        if cached is not None:
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    if not uncached_texts:
        return results  # type: ignore[return-value]

    # ── 推理 ──
    if settings.USE_LOCAL_EMBEDDING:
        # 本地模型：同步推理，放到线程池避免阻塞事件循环
        batch_vecs: list[list[float]] = await asyncio.to_thread(_local_embed_batch_sync, uncached_texts)
    else:
        # OpenAI API
        client = _get_openai_client()
        batch_vecs = []
        batch_size = 100
        for start in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[start: start + batch_size]
            resp = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=batch,
            )
            batch_vecs.extend([item.embedding for item in resp.data])

    # ── 写缓存 + 填充结果 ──
    for i, (orig_idx, text, vec) in enumerate(zip(uncached_indices, uncached_texts, batch_vecs)):
        key = _cache_key(text, model_tag)
        _write_cache(key, vec, ttl)
        results[orig_idx] = vec

    return results  # type: ignore[return-value]


async def get_embedding(text: str) -> list[float]:
    """单条便捷接口"""
    vecs = await get_embeddings([text])
    return vecs[0]
