# LifePilot — 家庭健康管理 AI 系统

> 用 AI 技术帮助家庭轻松管理健康，让每个成员都有自己的智能健康助理。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 功能概览

| 功能 | 状态 | 说明 |
|------|------|------|
| 🔐 家庭账户注册 / 登录 | ✅ 已完成 | JWT 认证，access + refresh token |
| 📱 微信小程序 | ⬜ 计庒中 | 日常用户端（uni-app），血压录入/问诊/检验单 |
| 📱 Flutter App | ⬜ 计庒中 | iOS/Android，适配老人大字体 UI |
| 💻 Web 管理后台 | ⬜ 计庒中 | React + Ant Design Pro，家庭健康总览 / 异常预警 || 📱 微信小程序 | ⬜ 计庒中 | 日常用户端（uni-app），血压录入/问诊/检验单 |
| 📱 Flutter App | ⬜ 计庒中 | iOS/Android，适配老人大字体 UI |
| 💻 Web 管理后台 | ⬜ 计庒中 | React + Ant Design Pro，家庭健康总览 / 异常銄警 || 📊 健康数据录入 | ⬜ 计划中 | 血压/血糖/体重/心率等 10 种指标 |
| 🔬 检验单 AI 解读 | ⬜ 计划中 | OCR 识别 + LLM 通俗解释异常项 |
| 💬 健康 RAG 问答 | ⬜ 计划中 | 基于权威知识库的智能问诊助手 |
| 💊 用药管理提醒 | ⬜ 计划中 | 智能提醒 + 依从性追踪 |
| 📈 慢病趋势预测 | ⬜ 计划中 | 时序模型预警血压/血糖异常趋势 |
| 📝 健康周报/月报 | ⬜ 计划中 | 自动生成家庭健康趋势报告 |

---

## 技术架构

```
FastAPI ──► PostgreSQL  （用户/成员/用药/报告）
        ──► InfluxDB    （血压/心率等时序数据）
        ──► Qdrant      （RAG 知识库向量检索）
        ──► Redis       （缓存/任务队列）
        ──► Celery      （OCR/LLM 异步任务）

微信小程序 ──► 日常用户端（血压录入/检验单/问诊）
Flutter App ─► iOS / Android（老人友好大字体 UI）
Web 管理后台 ► 家庭健康总览 / 异常预警 / 成员管理
```

详见 [doc/architecture.md](doc/architecture.md)

---

## 快速开始

### 前置条件

- Docker 24+
- Docker Compose 2.20+
- Git

### 1. 克隆仓库

```bash
git clone git@github.com:DJsummer/lifecopilot.git
cd lifecopilot
```

### 2. 配置环境变量

```bash
cp .env.example .env.dev
# 编辑 .env.dev，填写以下必要配置：
# - SECRET_KEY        JWT 签名密钥（随机字符串）
# - POSTGRES_PASSWORD 数据库密码
# - INFLUX_TOKEN      InfluxDB API Token
# - REDIS_PASSWORD    Redis 密码
# - OPENAI_API_KEY    LLM API 密钥
```

### 3. 启动开发环境（含热更新）

```bash
make dev
```

服务启动后访问：
- **API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health
- **InfluxDB 控制台**：http://localhost:8086
- **Qdrant 控制台**：http://localhost:6333/dashboard

### 4. 初始化数据库

```bash
make db-migrate    # 执行所有数据库迁移，创建表结构
```

---

## 常用命令

```bash
make dev           # 启动开发环境（热更新）
make dev-d         # 后台启动
make down          # 停止所有服务
make logs          # 查看所有日志
make logs-api      # 仅查看 API 日志
make shell         # 进入 API 容器
make db-migrate    # 执行数据库迁移
make db-shell      # 进入 PostgreSQL 交互终端
make test          # 在 Docker 中运行单元+集成测试
make test-local    # 在本地环境运行测试（需先 pip install -r requirements-test.txt）
make test-cov      # 生成测试覆盖率报告
make test-e2e      # 运行 Selenium E2E 测试
make lint          # 代码检查
make format        # 代码格式化
```

---

## 测试

项目使用 **pytest + pytest-asyncio** 进行后端测试，**Selenium** 进行 Web Admin E2E 测试。

```bash
# 安装测试依赖（仅需一次）
pip install -r requirements-test.txt

# 运行所有单元 + 集成测试
python -m pytest tests/ --ignore=tests/e2e -v

# 仅运行单元测试
python -m pytest tests/ -m unit -v

# 运行 E2E 测试（须先启动 Web Admin 服务）
python -m pytest tests/e2e/ --base-url=http://localhost:3000 -v

# 查看覆盖率
python -m pytest tests/ --ignore=tests/e2e --cov=src --cov-report=html
```

**测试状态**：44/44 通过 ✅（单元测试 11 + 集成测试 31 + 系统测试 2）

---

## 项目结构

```
lifecopilot/
├── src/
│   ├── main.py              # FastAPI 应用入口
│   ├── core/                # 配置 / 数据库 / 日志
│   ├── models/              # SQLAlchemy ORM 模型
│   ├── api/v1/routers/      # API 路由（待实现）
│   ├── services/            # 业务逻辑层（待实现）
│   └── workers/             # Celery 异步任务
├── alembic/                 # 数据库迁移脚本
├── docker/                  # 各服务配置文件
├── doc/                     # 设计文档
│   └── architecture.md      # 系统架构设计
├── tests/
│   ├── conftest.py          # pytest fixtures（SQLite in-memory + AsyncClient）
│   ├── test_security.py     # 安全模块单元测试（JWT/密码哈希）
│   ├── test_auth.py         # 认证 API 集成测试
│   ├── test_members.py      # 成员管理 API 集成测试
│   ├── test_system.py       # 系统健康检查测试
│   └── e2e/                 # Selenium E2E 测试（Web Admin）
├── Dockerfile               # 多阶段构建
├── docker-compose.yml       # 生产环境
├── docker-compose.dev.yml   # 开发环境（热更新）
├── Makefile                 # 快捷命令
├── requirements.txt         # Python 依赖
└── TASKS.md                 # 项目任务清单与进度
```

---

## 开发进度

详见 [TASKS.md](TASKS.md)

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| 阶段零：Docker 部署基础设施 | ✅ 已完成 | 100% |
| 阶段一：基础架构搭建 | ✅ 已完成 | 100% |
| 阶段二：核心健康监测 | ⬜ 未开始 | 0% |
| 阶段三：智能问诊助手（RAG） | ⬜ 未开始 | 0% |
| 阶段四：生活方式干预 | ⬜ 未开始 | 0% |
| 阶段五～七 | ⬜ 未开始 | 0% |

---

## 免责声明

本系统提供的所有 AI 分析结果（检验单解读、症状分析、用药建议等）**仅供参考，不构成医疗诊断意见**。如有健康问题请及时就医，遵从专业医生的建议。
