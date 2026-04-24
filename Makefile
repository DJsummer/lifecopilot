COMPOSE_BASE = docker-compose.yml
COMPOSE_DEV  = docker-compose.dev.yml
DC_DEV       = docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_DEV)
DC_PROD      = docker compose -f $(COMPOSE_BASE)

.PHONY: help dev prod down logs ps shell db-migrate build

help:          ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── 开发环境（热更新）────────────────────────────────────────────────
dev:           ## 启动开发环境（热更新）
	@[ -f .env.dev ] || (cp .env.example .env.dev && echo "请编辑 .env.dev 后重新运行")
	$(DC_DEV) up --build

dev-d:         ## 后台启动开发环境
	$(DC_DEV) up --build -d

dev-api:       ## 仅重启 API 服务
	$(DC_DEV) restart api

# ── 生产环境────────────────────────────────────────────────────────
prod:          ## 启动生产环境
	@[ -f .env ] || (echo "请先配置 .env 文件"; exit 1)
	$(DC_PROD) up -d

# ── 通用操作────────────────────────────────────────────────────────
down:          ## 停止所有服务
	$(DC_DEV) down

down-v:        ## 停止并清除所有数据卷（危险！）
	$(DC_DEV) down -v

logs:          ## 查看所有日志（实时）
	$(DC_DEV) logs -f

logs-api:      ## 查看 API 日志
	$(DC_DEV) logs -f api

ps:            ## 查看服务状态
	$(DC_DEV) ps

build:         ## 重新构建镜像
	$(DC_DEV) build --no-cache

# ── 数据库────────────────────────────────────────────────────────
db-migrate:    ## 运行 Alembic 数据库迁移
	$(DC_DEV) exec api alembic upgrade head

db-revision:   ## 创建新的迁移文件（需传 MSG=xxx）
	$(DC_DEV) exec api alembic revision --autogenerate -m "$(MSG)"

db-shell:      ## 进入 PostgreSQL 交互终端
	$(DC_DEV) exec postgres psql -U lifepilot -d lifepilot

# ── 调试────────────────────────────────────────────────────────
shell:         ## 进入 API 容器 bash
	$(DC_DEV) exec api bash

worker-shell:  ## 进入 Worker 容器 bash
	$(DC_DEV) exec worker bash

# ── 代码质量────────────────────────────────────────────────────────
lint:          ## 运行 ruff 代码检查
	$(DC_DEV) exec api ruff check src/

format:        ## 运行 ruff 格式化
	$(DC_DEV) exec api ruff format src/

test:          ## 运行所有单元+集成测试（排除 e2e）
	$(DC_DEV) exec api pytest tests/ -m "not e2e" -v

test-unit:     ## 仅运行单元测试
	$(DC_DEV) exec api pytest tests/ -m unit -v

test-integration: ## 仅运行集成测试
	$(DC_DEV) exec api pytest tests/ -m integration -v

test-cov:      ## 运行测试并生成覆盖率报告
	$(DC_DEV) exec api pytest tests/ -m "not e2e" --cov=src --cov-report=html:htmlcov

test-e2e:      ## 运行 Selenium 端到端测试（需前端在运行）
	$(DC_DEV) exec api pytest tests/e2e/ -m e2e --base-url $(E2E_URL) -v

test-local:    ## 本地直接运行测试（不通过 Docker）
	pip install -r requirements-test.txt -q
	pytest tests/ -m "not e2e" -v
