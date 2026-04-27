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

    # 皮肤/伤口视觉分析后端（T013）
    # openai  → 任何 OpenAI 兼容接口（GPT-4o / DeepSeek / Moonshot / Qwen API /
    #           Azure OpenAI / 智谱 GLM-4V 等），通过 SKIN_VISION_BASE_URL 切换供应商
    # ollama  → 本地 Ollama 服务（Qwen2-VL / LLaVA 等）
    # local   → 本地 transformers 推理（Qwen2-VL-Instruct，需 GPU 或足够内存）
    SKIN_VISION_BACKEND: str = "openai"
    SKIN_VISION_MODEL: str = "gpt-4o"              # 模型名，随供应商调整
    SKIN_VISION_LOCAL_MODEL: str = "Qwen/Qwen2-VL-7B-Instruct"  # local 模式 HF 模型名
    OLLAMA_BASE_URL: str = "http://ollama:11434"   # Ollama 服务地址
    # 皮肤视觉分析专用 API Key / Base URL（不填时回退到全局 OPENAI_API_KEY/BASE_URL）
    # 示例：
    #   DeepSeek-VL2:  SKIN_VISION_BASE_URL=https://api.deepseek.com/v1
    #                  SKIN_VISION_MODEL=deepseek-vl2
    #   Moonshot:      SKIN_VISION_BASE_URL=https://api.moonshot.cn/v1
    #                  SKIN_VISION_MODEL=moonshot-v1-8k-vision-preview
    #   Qwen VL API:   SKIN_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    #                  SKIN_VISION_MODEL=qwen-vl-plus
    #   Azure OpenAI:  SKIN_VISION_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deploy>/
    #                  SKIN_VISION_MODEL=gpt-4o
    #   智谱 GLM-4V:   SKIN_VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
    #                  SKIN_VISION_MODEL=glm-4v
    SKIN_VISION_API_KEY: str = ""   # 空 → 回退到 OPENAI_API_KEY
    SKIN_VISION_BASE_URL: str = ""  # 空 → 回退到 OPENAI_BASE_URL

    @property
    def _skin_api_key(self) -> str:
        return self.SKIN_VISION_API_KEY or self.OPENAI_API_KEY

    @property
    def _skin_base_url(self) -> str:
        return self.SKIN_VISION_BASE_URL or self.OPENAI_BASE_URL

    # 文件上传（检验单）
    UPLOAD_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_MB: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
