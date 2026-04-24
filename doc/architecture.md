# LifePilot — 系统架构设计文档

> 版本：v0.1  
> 日期：2026-04-24  
> 状态：进行中

---

## 1. 项目概述

LifePilot 是一套面向家庭的 AI 健康管理系统，核心目标是：

- 让家庭成员轻松记录和追踪健康数据
- 用 AI 辅助理解医疗报告、管理用药、识别健康风险
- 提供基于权威知识库的智能问诊助手

**最小可行产品（MVP）**：健康数据录入 + 检验单 AI 解读 + RAG 问答助手

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        客户端（前端）                             │
│           Web App / 微信小程序 / Mobile App                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Nginx（反向代理）                           │
│            TLS 终止 / 限流 / 静态资源                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI 应用层                                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  认证 / JWT  │  │  健康数据 API │  │  AI 服务 API           │  │
│  │  /api/v1/auth│  │  /api/v1/    │  │  RAG / OCR / LLM      │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Service 层                            │    │
│  │  MemberService / HealthService / MedicationService       │    │
│  │  LabReportService / RAGService / NotificationService     │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────┬──────────────┬──────────────────────┬────────────────────┘
       │              │                      │
       ▼              ▼                      ▼
┌────────────┐ ┌────────────────┐  ┌──────────────────────────────┐
│ PostgreSQL │ │   InfluxDB     │  │         Redis                 │
│            │ │                │  │                               │
│ 结构化数据  │ │  时序健康数据   │  │  缓存 / 会话 / 消息队列        │
│ 用户/成员/ │ │  血压/血糖/心率 │  │                               │
│ 用药/报告  │ │  步数/睡眠     │  └──────────────┬────────────────┘
└────────────┘ └────────────────┘                 │
                                                   ▼
                                       ┌───────────────────────┐
                                       │    Celery Worker       │
                                       │                        │
                                       │  周报生成 / 推送通知    │
                                       │  OCR 处理 / 模型推理   │
                                       └───────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    AI 基础设施层                                   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │    Qdrant    │  │  LLM 接口    │  │   PaddleOCR           │  │
│  │  向量数据库   │  │  GPT-4o /    │  │   检验单识别           │  │
│  │  RAG 知识库  │  │  Qwen        │  │                       │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 技术选型

### 3.1 后端

| 组件 | 技术 | 选型理由 |
|------|------|----------|
| Web 框架 | FastAPI | 原生异步、自动生成 OpenAPI 文档、性能高 |
| ORM | SQLAlchemy 2.0 (async) | 类型安全、异步支持、与 Alembic 深度集成 |
| 数据库迁移 | Alembic | 版本化管理表结构，支持回滚 |
| 配置管理 | pydantic-settings | 类型校验、`.env` 自动加载 |
| 结构化日志 | structlog | JSON 格式输出，便于日志收集 |
| 任务队列 | Celery + Redis | 异步任务（报告生成/OCR/通知） |
| 认证 | JWT (python-jose) | 无状态、适合多端同时登录 |

### 3.2 数据库

| 数据库 | 用途 | 理由 |
|--------|------|------|
| PostgreSQL 16 | 结构化数据（用户/成员/用药/报告） | 关系型、事务完整、UUID 原生支持 |
| InfluxDB 2.7 | 时序健康指标（血压/心率/血糖等） | 专为时序数据优化，查询聚合高效 |
| Qdrant | RAG 知识库向量索引 | 高性能向量检索，支持 payload 过滤 |
| Redis 7 | 缓存 / 会话 / Celery Broker | 低延迟，Celery 官方推荐 |

### 3.3 AI 组件

| 组件 | 技术 | 用途 |
|------|------|------|
| LLM | GPT-4o / Qwen（可配置） | 报告解读、症状分析、食谱生成 |
| Embedding | text-embedding-3-small | 知识库文本向量化 |
| RAG 框架 | LangChain | Pipeline 编排、文档检索 |
| OCR | PaddleOCR | 检验单/药盒图片文字识别 |
| 多模态 | GPT-4o Vision | 皮肤/伤口照片辅助分析 |

### 3.4 基础设施

| 组件 | 技术 | 说明 |
|------|------|------|
| 容器化 | Docker + Docker Compose | 多阶段构建，dev/prod 分离 |
| 热更新 | uvicorn `--reload` + volume 挂载 | 开发时代码改动秒生效 |
| 反向代理 | Nginx | TLS、限流、静态资源 |
| CI/CD | 待定（GitHub Actions） | 自动测试、镜像构建、部署 |

---

## 4. 数据库设计

### 4.1 PostgreSQL 数据模型

#### 数据模型关系图

```
Family
  │  1
  │  ──── n  Member
                │
                ├── n  HealthRecord       (血压/血糖/体重等单次记录)
                ├── n  SymptomLog         (症状日记 + NLP 结构化结果)
                ├── n  Medication         (用药方案)
                │        ├── n  MedicationReminder  (提醒时间配置)
                │        └── n  AdherenceLog        (服药依从性记录)
                └── n  LabReport          (检验报告 + OCR + LLM 解读)
```

#### 核心表说明

**`families`** — 家庭账户
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | VARCHAR(100) | 家庭名称 |
| invite_code | VARCHAR(16) | 邀请码（唯一） |
| created_at / updated_at | TIMESTAMPTZ | 时间戳 |

**`members`** — 家庭成员
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| family_id | UUID FK | 所属家庭 |
| nickname | VARCHAR(50) | 昵称 |
| role | ENUM | admin / adult / elder / child |
| gender | ENUM | male / female / other |
| birth_date | DATE | 生日（用于计算年龄、发育百分位） |
| email | VARCHAR(254) | 可选，登录邮箱（老人/儿童可为空） |
| hashed_password | VARCHAR(200) | bcrypt 哈希 |

**`health_records`** — 健康指标记录
| 字段 | 类型 | 说明 |
|------|------|------|
| member_id | UUID FK | 成员 |
| metric_type | ENUM | blood_pressure_sys/dia, heart_rate, blood_glucose, weight, height, body_temperature, spo2, steps, sleep_hours |
| value | FLOAT | 数值 |
| unit | VARCHAR(20) | mmHg / bpm / mmol/L / kg 等 |
| measured_at | TIMESTAMPTZ | 测量时间（索引） |
| source | VARCHAR(50) | manual / wearable / import |

**`lab_reports`** — 检验单报告
| 字段 | 类型 | 说明 |
|------|------|------|
| report_type | ENUM | blood_routine / biochemistry / urine_routine / lipid_panel 等 |
| file_path | VARCHAR(500) | 上传文件存储路径 |
| ocr_raw_text | TEXT | PaddleOCR 识别原文 |
| structured_data | TEXT (JSON) | LLM 结构化的指标键值对 |
| llm_interpretation | TEXT | LLM 生成的通俗解读 |
| abnormal_items | TEXT (JSON) | 异常项数组 |
| has_abnormal | BOOLEAN | 快速过滤标志 |

### 4.2 InfluxDB 数据结构

时序数据存储健康指标的连续监测值（适合趋势分析、聚合查询）：

```
Measurement: health_metrics
Tags:
  - member_id: string
  - metric_type: string   (blood_pressure_sys, heart_rate, ...)
  - source: string        (manual, wearable)
Fields:
  - value: float
Timestamp: RFC3339
```

查询示例（过去 7 天血压趋势）：
```flux
from(bucket: "health_metrics")
  |> range(start: -7d)
  |> filter(fn: (r) => r["member_id"] == "xxx" and r["metric_type"] == "blood_pressure_sys")
  |> aggregateWindow(every: 1d, fn: mean)
```

### 4.3 Qdrant 集合设计

```
Collection: health_knowledge
Vector dimension: 1536  (text-embedding-3-small)
Distance: Cosine

Payload schema:
  - source: string        (丁香医生 / 默沙东手册 / ...)
  - category: string      (症状 / 用药 / 检验 / 营养 / ...)
  - title: string
  - chunk_index: int
  - updated_at: string
```

---

## 5. API 设计

### 5.1 URL 规范

```
/api/v1/{resource}
```

### 5.2 核心端点（规划）

#### 认证
```
POST   /api/v1/auth/register          注册家庭账户
POST   /api/v1/auth/login             登录，返回 JWT
POST   /api/v1/auth/refresh           刷新 token
```

#### 成员管理
```
GET    /api/v1/members                获取家庭成员列表
POST   /api/v1/members                添加成员
GET    /api/v1/members/{id}           成员详情
PATCH  /api/v1/members/{id}           更新成员信息
DELETE /api/v1/members/{id}           删除成员
```

#### 健康数据
```
POST   /api/v1/members/{id}/records   录入健康指标
GET    /api/v1/members/{id}/records   查询历史记录（支持时间范围/指标类型过滤）
POST   /api/v1/members/{id}/records/import  批量导入 CSV
```

#### 检验单
```
POST   /api/v1/members/{id}/reports   上传检验单（图片/PDF）→ 触发 OCR + LLM 解读
GET    /api/v1/members/{id}/reports   报告列表
GET    /api/v1/members/{id}/reports/{rid}  报告详情（含 LLM 解读）
```

#### 用药管理
```
POST   /api/v1/members/{id}/medications         添加用药方案
GET    /api/v1/members/{id}/medications         用药列表
PATCH  /api/v1/members/{id}/medications/{mid}   更新用药状态
POST   /api/v1/members/{id}/medications/{mid}/adherence  记录服药情况
```

#### AI 问答
```
POST   /api/v1/chat                   RAG 问答（支持多轮对话）
GET    /api/v1/chat/history           对话历史
```

#### 系统
```
GET    /health                        健康检查（公开）
```

### 5.3 通用响应格式

```json
{
  "data": { ... },
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100
  }
}
```

错误响应：
```json
{
  "detail": {
    "code": "MEMBER_NOT_FOUND",
    "message": "指定的家庭成员不存在"
  }
}
```

---

## 6. AI 流程设计

### 6.1 检验单解读流程

```
用户上传图片/PDF
      │
      ▼
文件校验（类型/大小）
      │
      ▼
存储文件（本地/OSS）
      │
      ▼
Celery 异步任务
      │
      ├── PaddleOCR → 提取文本
      │
      ├── LLM Prompt:
      │   "以下是医学检验单原文，请：
      │    1. 提取所有检验项目和数值（JSON格式）
      │    2. 标注超出参考范围的异常项
      │    3. 用通俗语言解释报告含义"
      │
      └── 结果写回 lab_reports 表 → WebSocket 推送通知前端
```

### 6.2 RAG 问答流程

```
用户提问
      │
      ▼
安全过滤（健康领域外问题拒绝）
      │
      ▼
Embedding（text-embedding-3-small）
      │
      ▼
Qdrant 向量检索（top-k=5）
      │
      ▼
构建 Prompt:
  [系统] 你是家庭健康助手，仅根据以下资料回答...
  [知识] {检索到的文档片段}
  [历史] {多轮对话历史}
  [用户] {当前问题}
      │
      ▼
LLM 生成回答（附带知识来源引用）
      │
      ▼
存储对话历史（Redis，TTL 30天）
```

### 6.3 异常阈值预警规则

```python
# 示例：高血压预警规则（可按成员个性化配置）
ALERT_RULES = {
    "blood_pressure_sys": {"warning": 140, "critical": 180},
    "blood_pressure_dia": {"warning": 90,  "critical": 120},
    "blood_glucose":      {"warning": 7.8, "critical": 11.1},
    "heart_rate":         {"warning": 100, "critical": 130},
    "body_temperature":   {"warning": 37.5,"critical": 38.5},
}
```

---

## 7. 部署架构

### 7.1 开发环境

```bash
make dev   # 启动所有服务（含热更新）
```

- API 容器：uvicorn `--reload`，挂载 `./src` 实现代码热更新
- Worker 容器：`watchfiles` 监听，代码改动自动重启
- 所有数据库暴露端口，方便本地工具直连调试

### 7.2 Docker 服务拓扑

```
docker-compose.yml (生产)
  ├── api         : lifepilot-api:latest (4 workers)
  ├── worker      : lifepilot-api:latest (celery)
  ├── nginx       : nginx:alpine
  ├── postgres    : postgres:16-alpine
  ├── influxdb    : influxdb:2.7-alpine
  ├── qdrant      : qdrant/qdrant:latest
  └── redis       : redis:7-alpine

docker-compose.dev.yml (开发覆盖层)
  ├── api         : development target + volume ./src:/app/src
  ├── worker      : development target + watchfiles
  └── nginx       : disabled (profile: prod-only)
```

### 7.3 环境变量

所有敏感配置通过 `.env` 文件注入，详见 `.env.example`。
核心变量：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT 签名密钥（生产须随机生成） |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 |
| `INFLUX_TOKEN` | InfluxDB API Token |
| `OPENAI_API_KEY` | LLM API 密钥 |
| `REDIS_PASSWORD` | Redis 认证密码 |

---

## 8. 安全设计

| 风险 | 措施 |
|------|------|
| SQL 注入 | SQLAlchemy ORM 参数化查询，禁止拼接原始 SQL |
| 未授权访问 | JWT + 家庭成员资源鉴权（只能访问自己家庭数据） |
| 敏感数据泄露 | 密码 bcrypt 哈希存储；`.env` 不入 Git |
| 文件上传风险 | 类型白名单（PDF/JPG/PNG）、大小限制（10MB） |
| LLM 提示注入 | 用户输入经过清洗；系统 prompt 固定不可覆盖 |
| 医疗免责 | 所有 AI 分析结果附加免责声明，不替代专业诊断 |
| 速率限制 | Nginx + FastAPI 双层限流防止滥用 |

---

## 9. 目录结构

```
lifepilot/
├── Dockerfile                   # 多阶段构建
├── docker-compose.yml           # 生产环境
├── docker-compose.dev.yml       # 开发热更新覆盖层
├── Makefile                     # 快捷命令
├── requirements.txt             # Python 依赖
├── alembic.ini                  # Alembic 配置
├── .env.example                 # 环境变量模板
│
├── alembic/                     # 数据库迁移脚本
│   ├── env.py                   # 迁移环境配置
│   └── versions/                # 各版本迁移文件
│
├── docker/
│   ├── postgres/init.sql        # 数据库初始化
│   ├── nginx/nginx.conf         # Nginx 配置
│   └── qdrant/config.yaml      # Qdrant 配置
│
├── src/
│   ├── main.py                  # FastAPI 应用入口
│   ├── core/
│   │   ├── config.py            # pydantic-settings 配置
│   │   ├── database.py          # 异步数据库连接
│   │   └── logging.py           # structlog 配置
│   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── base.py              # 基础模型（UUID主键+时间戳）
│   │   ├── member.py            # Family / Member
│   │   ├── health.py            # HealthRecord / SymptomLog
│   │   ├── medication.py        # Medication / Reminder / Adherence
│   │   └── report.py            # LabReport
│   ├── api/v1/routers/          # 路由处理器（待实现）
│   ├── services/                # 业务逻辑层（待实现）
│   └── workers/
│       ├── celery_app.py        # Celery 应用实例
│       └── tasks/               # 异步任务（报告生成/通知）
│
├── tests/                       # 单元 & 集成测试
├── scripts/                     # 运维脚本
└── doc/                         # 设计文档
    └── architecture.md          # 本文档
```

---

## 10. 待决策项

| 问题 | 待选方案 | 优先级 |
|------|----------|--------|
| 前端技术栈 | 微信小程序 vs Flutter vs React Native | P1 |
| 文件存储 | 本地卷 vs 阿里云 OSS vs MinIO | P1 |
| LLM 供应商 | OpenAI GPT-4o vs 阿里云 Qwen（成本更低） | P0 |
| 推送通知 | 微信模板消息 vs Firebase FCM vs 邮件 | P2 |
| 部署平台 | 阿里云 ECS vs 腾讯云 vs 自建 | P2 |
