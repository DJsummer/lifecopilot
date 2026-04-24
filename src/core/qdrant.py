"""Qdrant 向量数据库客户端单例"""
from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from src.core.config import settings

# ── Collection 常量 ───────────────────────────────────────────────────
HEALTH_KNOWLEDGE_COLLECTION = "health_knowledge"
EMBEDDING_DIM = 1536  # text-embedding-3-small


def get_qdrant_client() -> AsyncQdrantClient:
    """返回 Qdrant 异步客户端（每次调用返回同一实例）"""
    return AsyncQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        timeout=30,
    )


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
