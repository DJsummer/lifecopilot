# =====================================================================
# Stage 1: base — 公共依赖层
# =====================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 系统依赖（OCR、图像处理等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# =====================================================================
# Stage 2: builder — 安装 Python 依赖
# =====================================================================
FROM base AS builder

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# =====================================================================
# Stage 3: development — 支持热更新（挂载源码）
# =====================================================================
FROM base AS development

COPY --from=builder /install /usr/local

WORKDIR /app

# dev 阶段不 COPY 源码，由 docker-compose volume 挂载实现热更新
EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/src", "--log-level", "debug"]

# =====================================================================
# Stage 4: production — 精简镜像
# =====================================================================
FROM base AS production

COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY scripts/ ./scripts/

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--log-level", "info"]
