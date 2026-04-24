"""Qdrant 向量数据库客户端单例"""
from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from src.core.config import settings

# ── Collection 常量 ───────────────────────────────────────────────────
HEALTH_KNOWLEDGE_COLLECTION = "health_knowledge"

# 从 settings 读取 dim，支持切换模型（OpenAI=1536，bge-m3=1024，bge-base-zh=768）
EMBEDDING_DIM: int = settings.EMBEDDING_DIM

_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """返回 Qdrant 异步客户端（单例）"""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=30,
        )
    return _client


async def ensure_collection(client: AsyncQdrantClient) -> None:
    """若 collection 不存在则创建"""
    existing = {c.name for c in (await client.get_collections()).collections}
    if HEALTH_KNOWLEDGE_COLLECTION not in existing:
        await client.create_collection(
            collection_name=HEALTH_KNOWLEDGE_COLLECTION,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
