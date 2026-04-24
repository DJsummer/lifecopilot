from __future__ import annotations
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 应用
    ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]

    # PostgreSQL
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "lifepilot"
    POSTGRES_USER: str = "lifepilot"
    POSTGRES_PASSWORD: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # InfluxDB
    INFLUX_URL: str = "http://influxdb:8086"
    INFLUX_TOKEN: str
    INFLUX_ORG: str = "lifepilot"
    INFLUX_BUCKET: str = "health_metrics"

    # Qdrant
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Embedding — 本地推理选项
    # USE_LOCAL_EMBEDDING=true 时使用本地 bge-m3，false 时走 OpenAI API
    USE_LOCAL_EMBEDDING: bool = False
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"          # cpu / cuda / mps
    EMBEDDING_BATCH_SIZE: int = 32
    HF_CACHE_DIR: str = "/app/models"
    EMBEDDING_DIM: int = 1536              # 1536=OpenAI，1024=bge-m3，768=bge-base-zh
    EMBEDDING_CACHE_TTL: int = 86400 * 7  # Embedding 缓存 7 天

    # 检索增强
    USE_RERANKER: bool = False             # CrossEncoder rerank（需 sentence-transformers）
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    QUERY_CACHE_TTL: int = 300             # 查询结果缓存 5 分钟（Redis）


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
