# LifePilot — 系统架构设计文档

> 版本：v1.4  
> 日期：2026-05-01  
> 状态：进行中  
> 变更：T007（児童生长发育评估）完成，407 个测试全部通过

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

## 3. 技术选型与选型理由

### 3.1 后端框架

#### FastAPI（Web 框架）

**选择理由**：

- **原生异步**：Python `async/await` 支持，能在等待数据库/LLM 响应时释放线程，适合健康数据录入 + AI 推理并发场景
- **自动生成 OpenAPI 文档**：`/docs` 开箱即用，前端/移动端联调成本极低
- **Pydantic 集成**：请求体自动校验，用户输入的血压值、日期等在进入业务逻辑前已完成类型校验，大幅降低注入风险
- **对比 Django**：Django ORM 不支持异步，且全家桶模式引入大量本项目不需要的模板/Admin 功能；FastAPI 更轻量聚焦

#### SQLAlchemy 2.0 async（ORM）

**选择理由**：

- **防 SQL 注入**：参数化查询自动处理，健康数据属于敏感数据，禁止拼接原始 SQL
- **类型安全**：Python 类描述表结构，字段拼写错误在 IDE 静态检查阶段即发现，而非运行时
- **关系导航**：`member.health_records` 直接访问关联数据，无需手写 JOIN
- **与 Alembic 深度集成**：模型变更只需改 Python 类，Alembic 自动 diff 生成 ALTER TABLE 脚本

#### Alembic（数据库迁移）

**选择理由**：

LifePilot 数据模型会持续演进（MVP → 慢病预测 → RAG → 用药管理），Alembic 相当于数据库表结构的 Git：

```bash
make db-revision MSG="add spo2 column"  # 自动生成迁移脚本
make db-migrate                          # 应用到数据库
alembic downgrade -1                     # 回滚上一步（无需手写 DROP）
```

生产环境上线新功能时，数据库变更有完整历史记录，出问题可精确回滚，不会丢失用户数据。

#### Celery + Redis（异步任务队列）

**选择理由**：

OCR 识别、LLM 推理、周报生成都是耗时操作（秒级到分钟级），不能阻塞 HTTP 请求：

```
用户上传检验单 → API 立即返回 202 Accepted
                → Celery Worker 异步跑 OCR + LLM
                → 完成后 WebSocket 推送通知
```

Redis 同时承担 Celery Broker 和结果存储，减少外部依赖数量。

---

### 3.2 数据库选型

#### PostgreSQL 16（结构化数据）

**选择理由**：

| 需求 | PostgreSQL 的支持 |
|------|------------------|
| 用户/成员/用药的关系型查询 | 完善的外键、JOIN、事务 |
| 主键唯一性保证 | UUID 原生支持（`uuid-ossp` 扩展） |
| 密码安全存储 | `pgcrypto` 提供 bcrypt 函数 |
| 数据完整性 | 严格的 ACID 事务，健康数据不会半写入 |
| JSON 字段（LLM 结构化结果） | `JSONB` 类型，支持索引检索 |

**为什么不用 MySQL**：MySQL 对 UUID 主键性能较差，JSON 支持不如 PostgreSQL 完善；PostgreSQL 在复杂查询和扩展性上更优。

#### InfluxDB 2.7（时序健康数据）

**选择理由**：

健康指标（血压/血糖/心率/步数）本质是时序数据，有特殊查询模式：

- "过去 30 天每日平均血压" → 时间范围聚合
- "血压趋势是否在上升" → 滑动窗口分析
- "连续 7 天步数低于 5000 步" → 条件告警

这类查询在 PostgreSQL 中需要复杂 SQL + 额外索引，而 InfluxDB 专为此设计，Flux 查询语言一行搞定：

```flux
from(bucket: "health_metrics")
  |> range(start: -30d)
  |> filter(fn: (r) => r["metric_type"] == "blood_pressure_sys")
  |> aggregateWindow(every: 1d, fn: mean)
  |> movingAverage(n: 7)
```

**职责分离**：PostgreSQL 存"某次测量的元数据"（谁测的、用什么设备），InfluxDB 存"时间序列的数值流"，各司其职。

#### Qdrant（向量数据库）

**选择理由**：

RAG 问答助手需要在健康知识库中快速找到与用户问题最相关的文档片段，这是向量相似度检索场景。

**为什么不用 pgvector（PostgreSQL 扩展）**：

| | Qdrant | pgvector |
|-|--------|---------|
| 实现语言 | Rust（高性能） | C（PostgreSQL 扩展） |
| 大规模检索 | HNSW 专用索引，百万向量毫秒级响应 | 混在关系型负载中，互相竞争资源 |
| Payload 过滤 | **在 HNSW 索引内部同时过滤**，精度不打折 | 先检索再 WHERE 过滤，召回率下降 |
| 独立扩展 | 向量库可单独扩展内存/CPU | 与主库绑定，难以独立扩容 |

**Payload 过滤是关键**：用户问"血糖偏高吃什么"时，应只检索营养类文档，而不是在全库搜索后再过滤：

```python
results = client.search(
    collection_name="health_knowledge",
    query_vector=embedding,
    query_filter=Filter(
        must=[FieldCondition(key="category", match=MatchValue(value="nutrition"))]
    ),
    limit=5
)
```

**为什么不用 Pinecone（云托管）**：健康知识库属于自建数据资产，且医疗类数据有隐私合规要求，不适合上传到第三方 SaaS，Qdrant 自托管完全数据自主。

**为什么不用 Chroma**：Chroma 定位是开发调试工具，Qdrant 才是面向生产的独立服务；本项目需要长期稳定运行。

#### Redis 7（缓存 / 会话 / 消息队列）

**选择理由**：

- **Celery Broker**：Celery 官方推荐，任务投递低延迟，ACK 机制保证任务不丢失
- **对话历史缓存**：RAG 问答的多轮历史存 Redis（TTL 30天），比数据库查询快 10-100 倍
- **JWT 黑名单**：用户登出后将 token 加入 Redis 黑名单，实现即时失效
- **一库多用**：一个 Redis 实例同时承担三种职责，减少运维复杂度

---

### 3.3 AI 组件

| 组件 | 技术 | 选型理由 |
|------|------|----------|
| LLM | GPT-4o / Qwen（可配置） | 通过环境变量切换，国内可用 Qwen 降低成本，接口兼容 OpenAI SDK |
| Embedding | text-embedding-3-small | 性价比最优，1536 维，中文支持好，成本约为 large 的 1/5 |
| RAG 框架 | LangChain | 成熟的 Pipeline 编排，内置文档分块/检索/历史管理，社区活跃 |
| OCR | PaddleOCR | 百度开源，中文检验单识别准确率业界领先，本地运行无 API 费用 |
| 皮肤视觉分析 | GPT-4o Vision / Ollama / 本地 Qwen2-VL | 逺过 `SKIN_VISION_BACKEND` 切换，支持多供应商 Key |

---

### 3.4 基础设施

#### Docker 多阶段构建

**选择理由**：开发和生产环境保持一致，消除"在我电脑上能跑"问题；多阶段构建使生产镜像不含开发工具，体积更小、攻击面更小。

**热更新方案**：
```yaml
# docker-compose.dev.yml
volumes:
  - ./src:/app/src   # 挂载源码到容器
command: uvicorn src.main:app --reload --reload-dir /app/src
```
代码保存 → uvicorn 检测文件变更 → 自动重启，无需重新 build 镜像，开发体验与本地无异。

#### Nginx（反向代理）

**选择理由**：
- TLS 终止：证书管理在 Nginx 层统一处理，应用层无需关心 HTTPS
- 限流：`limit_req_zone` 防止 API 滥用（LLM 调用成本高，需严格限流）
- 静态资源：前端构建产物直接由 Nginx 服务，不占用 FastAPI 进程

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
                ├── n  LabReport          (检验报告 + OCR + LLM 解读)
                ├── n  HealthReport       (周报/月报 + LLM 总结)
                ├── n  VisitSummary       (就医准备摘要)
                ├── n  MentalHealthLog    (PHQ-9/GAD-7 量表 + 情绪日记)
                ├── n  SkinAnalysis       (皮肤/伤口照片分析记录)
                ├── 1  NutritionGoal      (营养目标，每人唯一)
                ├── n  MealPlan           (每周食谱)
                ├── n  DietLog            (饮食日志记录)
                ├── 1  FitnessAssessment  (体能评估问卷，每人唯一)   ← T015
                ├── n  ExercisePlan       (LLM 生成的运动计划)               ← T015
                ├── n  WorkoutLog         (运动记录日志)                       ← T015
                ├── n  HealthThreshold    (个性化健康阈值配置)              ← T005
                ├── n  HealthAlert        (健康超阈预警记录)                 ← T005
                ├── n  HealthTrendSnapshot(趋势分析快照)                      ← T005
                ├── n  SleepRecord        (睡眠分期+评分+呼吸暂停风险)           ← T006
                ├── n  GrowthRecord       (WHO 百分位+Z-score+生长评分)         ← T007
                └── n  DevelopmentMilestone (发育里程碑追踪)                  ← T007

FoodItem  (食物营养素数据库，独立表)
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

#### 认证（✅ 已实现）
```
POST   /api/v1/auth/register          注册家庭账户（同时创建 admin 成员）
POST   /api/v1/auth/login             登录，返回 access + refresh token
POST   /api/v1/auth/refresh           无感刷新 access token
GET    /api/v1/auth/me                当前登录成员信息
GET    /api/v1/auth/family            家庭信息 + 成员列表（仅 admin）
POST   /api/v1/auth/family/members    添加家庭成员（仅 admin）
PATCH  /api/v1/auth/family/members/{id}  更新成员信息（自己或 admin）
DELETE /api/v1/auth/family/members/{id}  删除成员（仅 admin，不能删自己）
```

**Token 策略**：
- `access_token`：有效期 24h，携带 `member_id` / `family_id` / `role`
- `refresh_token`：有效期 30 天，仅含 `member_id`，用于静默续签
- 密码：bcrypt 哈希存储，不可逆

**权限层级**：
```
admin  → 可操作家庭内所有成员数据
adult  → 只能访问/修改自己的数据
elder  → 同 adult（特殊健康关注标记）
child  → 同 adult（生长发育追踪）
```

#### 成员管理
```
GET    /api/v1/members                获取家庭成员列表
POST   /api/v1/members                添加成员
GET    /api/v1/members/{id}           成员详情
PATCH  /api/v1/members/{id}           更新成员信息
DELETE /api/v1/members/{id}           删除成员
```

#### 健康数据（✅ 已实现 T004）
```
POST   /api/v1/health/{member_id}/records            单条录入（含异常值校验）
POST   /api/v1/health/{member_id}/records/batch      批量录入（JSON，≤500 条）
POST   /api/v1/health/{member_id}/records/import-csv CSV 批量导入历史数据（≤5MB）
GET    /api/v1/health/{member_id}/records            记录列表（按类型/时间过滤+分页）
DELETE /api/v1/health/{member_id}/records/{rid}      删除单条记录
GET    /api/v1/health/{member_id}/summary            各指标统计摘要（最近 N 天）
```

**值域校验**（异常值直接拒绝，返回 422）：

| 指标 | 单位 | 最小值 | 最大值 |
|------|------|--------|--------|
| blood_pressure_sys | mmHg | 50 | 300 |
| blood_pressure_dia | mmHg | 30 | 200 |
| heart_rate | bpm | 20 | 300 |
| blood_glucose | mmol/L | 1.0 | 50.0 |
| weight | kg | 1.0 | 500.0 |
| height | cm | 20.0 | 300.0 |
| body_temperature | °C | 30.0 | 45.0 |
| spo2 | % | 50.0 | 100.0 |
| steps | 步 | 0 | 200000 |
| sleep_hours | h | 0 | 24 |

#### 检验单 AI 解读（✅ 已完成 T012）
```
POST   /api/v1/lab-reports/{member_id}/upload           上传检验单（JPG/PNG/PDF/TXT）+ AI 解读
GET    /api/v1/lab-reports/{member_id}                  报告列表（按类型过滤）
GET    /api/v1/lab-reports/{member_id}/{report_id}      报告详情（含结构化项目）
DELETE /api/v1/lab-reports/{member_id}/{report_id}      删除报告
GET    /api/v1/lab-reports/{member_id}/compare          异常项趋势对比
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

#### 运动方案生成与追踪（✅ 已完成 T015）
```
POST   /api/v1/fitness/{member_id}/assessment         创建/更新体能评估问卷
GET    /api/v1/fitness/{member_id}/assessment         获取体能评估
POST   /api/v1/fitness/{member_id}/plans              LLM 生成本周运动计划
GET    /api/v1/fitness/{member_id}/plans              计划列表
GET    /api/v1/fitness/{member_id}/plans/active       当前活跃计划
POST   /api/v1/fitness/{member_id}/logs               记录运动日志（METs 热量 + LLM 反馈）
GET    /api/v1/fitness/{member_id}/logs               日志列表
GET    /api/v1/fitness/{member_id}/logs/{id}          日志详情
DELETE /api/v1/fitness/{member_id}/logs/{id}          删除日志
GET    /api/v1/fitness/{member_id}/summary/weekly     每周运动汇总统计
```

#### 慢病趋势预测与告警（✅ 已完成 T005）
```
GET    /api/v1/alerts/{member_id}/thresholds/defaults 查看系统默认阈值
POST   /api/v1/alerts/{member_id}/thresholds          设置/更新个性化阈值
GET    /api/v1/alerts/{member_id}/thresholds          阈值列表
DELETE /api/v1/alerts/{member_id}/thresholds/{metric} 删除阈值（恢复默认）
GET    /api/v1/alerts/{member_id}/alerts              告警列表（多维过滤）
GET    /api/v1/alerts/{member_id}/alerts/{id}         告警详情
PATCH  /api/v1/alerts/{member_id}/alerts/{id}/acknowledge  确认告警
DELETE /api/v1/alerts/{member_id}/alerts/{id}         删除告警
POST   /api/v1/alerts/{member_id}/trends              生成趋势快照（LLM 解读可选）
GET    /api/v1/alerts/{member_id}/trends              趋势快照列表
GET    /api/v1/alerts/{member_id}/trends/latest       某指标最新快照
```

#### 睡眠质量分析（✅ 已完成 T006）
```
POST   /api/v1/sleep/{member_id}/records         录入睡眠数据（自动评分 + LLM 建议）
GET    /api/v1/sleep/{member_id}/records         记录列表（可按 quality 过滤）
GET    /api/v1/sleep/{member_id}/records/{id}    记录详情
DELETE /api/v1/sleep/{member_id}/records/{id}    删除记录
GET    /api/v1/sleep/{member_id}/summary         近 N 天趋势汇总统计
```

#### 児童生长发育评估（✅ 已完成 T007）
```
POST   /api/v1/growth/{member_id}/records              录入身高/体重（WHO LMS 百分位 + LLM 评估）
GET    /api/v1/growth/{member_id}/records              生长记录列表
GET    /api/v1/growth/{member_id}/records/{id}         记录详情
DELETE /api/v1/growth/{member_id}/records/{id}         删除记录
POST   /api/v1/growth/{member_id}/milestones/init      初始化预设里程碑（24 条）
POST   /api/v1/growth/{member_id}/milestones           添加自定义里程碑
GET    /api/v1/growth/{member_id}/milestones           里程碑列表（可按类型/状态过滤）
PATCH  /api/v1/growth/{member_id}/milestones/{id}/achieve 标记已达成
DELETE /api/v1/growth/{member_id}/milestones/{id}      删除自定义里程碑
GET    /api/v1/growth/{member_id}/summary              生长发育概览
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

### 6.2 RAG 问答流程（✅ 已实现 T009/T010）

```
用户提问
      │
      ▼
安全过滤（敏感词拦截 + 非健康类问题拒绝）
      │
      ▼
Embedding（OpenAI text-embedding-3-small）
      │
      ▼
Qdrant 向量检索（top_k 可配置，默认 4）
  - 返回最相似的健康知识片段
  - 可按 category 过滤（内科/儿科等）
      │
      ▼
构建 RAG Prompt:
  [system] LifePilot 家庭健康助手角色设定 + 免责声明
  [system] 成员健康背景（可选）
  [知识]   检索到的文档片段（含来源引用）
  [历史]   多轮对话历史（最近 10 轮）
  [user]   当前用户问题
      │
      ├── 同步模式: POST /api/v1/chat/
      │         → 完整回答一次性返回
      │
      └── 流式模式: POST /api/v1/chat/stream
                → SSE 逐 token 推送，前端实时展示
      │
      ▼
返回：answer + sources（知识来源列表）+ session_id

会话管理：内存存储（最大 10000 会话，LRU 淘汰）
           生产环境建议迁移至 Redis（TTL 30天）
```

**知识库管理 API**（仅 admin）：
```
POST   /api/v1/chat/knowledge       摄入文档（分块 + Embedding + 存入 Qdrant）
DELETE /api/v1/chat/knowledge/{src} 删除指定来源所有向量
GET    /api/v1/chat/knowledge/stats 知识库统计（向量数/点数/状态）
```

**文本分块策略**：
- 编码器：`cl100k_base`（GPT-4/Embedding 通用）
- 默认 chunk_size：512 tokens，overlap：64 tokens
- 使用 MD5 哈希作为 Qdrant Point ID，支持幂等 upsert

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

## 10. 前端架构

### 10.1 三端方案总览

| 端 | 技术 | 目标用户 | 核心场景 |
|----|------|----------|----------|
| 微信小程序 | uni-app | 全家庭日常用户 | 快速录入健康数据、问诊、检验单上传 |
| Flutter App | Flutter 3 | 老人 / 长期用户 | 大字体友好、趋势图表、离线缓存 |
| Web 管理后台 | React 18 + Ant Design Pro | 家庭管理员 | 全员健康总览、异常预警、报告管理 |

### 10.2 微信小程序（uni-app）

**选型理由**：国内用户无需下载 App，微信扫码即用；uni-app 同时编译 H5，可作为 Web 备用入口。

主要页面：
```
首页         → 家庭成员健康卡片快速概览
录入         → 血压/血糖/体重一键录入（支持语音）
问诊         → RAG 健康问答聊天界面
检验单       → 拍照上传 → 等待 AI 解读 → 结果展示
我的         → 个人档案 / 用药提醒设置
```

推送：微信服务通知（用药提醒、异常预警）

### 10.3 Flutter App

**选型理由**：一套代码跨 iOS/Android；Dart 类型系统健壮；老人友好 UI 定制灵活度高。

核心特性：
- **大字体模式**：字号 20px 起，高对比度配色
- **离线缓存**：近 7 天数据本地存储，无网络也可查看历史
- **趋势图表**：`fl_chart` 绘制血压/血糖折线图
- **生物认证**：指纹/Face ID 快速登录（老人更友好）

### 10.4 Web 管理后台

**选型理由**：大屏展示家庭整体健康状况，数据密度高，需要复杂表格/图表，Web 端最合适。

技术栈：`React 18 + Ant Design Pro 5 + ECharts + React Query`

核心模块：
```
Dashboard    → 家庭全员关键指标卡片 + 近期异常列表
成员管理      → 添加/编辑/删除成员，角色权限配置
健康记录      → 时序折线图（血压/血糖趋势）+ 数据表格
检验单管理    → 报告列表 + AI 解读详情 + 历史对比
用药管理      → 用药方案 + 依从性统计饼图
报告中心      → 周报/月报在线预览 + PDF 导出
预警中心      → 未读异常通知 + 处理状态跟踪
```

部署：Nginx 直接服务 `build/` 静态文件，与 API 共用 Docker Compose。

---

## 11. 测试策略

### 11.1 分层测试

| 层次 | 工具 | 范围 | 状态 |
|------|------|------|------|
| 单元测试 | pytest | security.py（JWT/密码哈希） | ✅ 11 用例 |
| 集成测试 | pytest + httpx AsyncClient | 所有 API 端点 | ✅ 31 用例 |
| E2E 测试 | Selenium + Chrome | Web Admin 登录/Dashboard | 🔄 框架就绪 |

**当前通过率：82/82（100%）**

### 11.2 测试基础设施

- **SQLite in-memory**：集成测试不依赖外部数据库，每用例通过事务回滚完全隔离
- **AsyncClient + ASGITransport**：无需真实 HTTP 服务，直接测试 ASGI 应用层
- **pytest-asyncio**（`asyncio_mode=auto`）：所有测试函数均可为 `async def`
- **python-dotenv**：conftest.py 启动时加载 `.env.test`，与生产配置完全隔离
- **webdriver-manager**：Selenium 自动下载 ChromeDriver，无需手动维护驱动版本

### 11.3 已知约束与修复记录

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| `X \| None` 语法错误 | Python 3.9 不支持 `X \| Y` union 运算符 | 全局替换为 `Optional[X]`（`typing` 模块） |
| SQLAlchemy `Mapped[]` 报错 | `from __future__ import annotations` 使注解变字符串 | ORM 模型文件不加此 import，非 ORM 文件保留 |
| bcrypt `__about__` 错误 | bcrypt ≥4.0 移除了 `__about__` 属性，passlib 1.7.4 不兼容 | 降级至 `bcrypt==3.2.2` |
| `MissingGreenlet` 懒加载 | async session 关闭后 FastAPI 序列化触发关系属性懒加载 | 改用 `selectinload()` 急加载关联关系 |

### 11.4 运行方式

```bash
# 本地运行（推荐）
pip install -r requirements-test.txt
python -m pytest tests/ --ignore=tests/e2e -v

# Docker 中运行
make test

# 覆盖率报告
python -m pytest tests/ --ignore=tests/e2e --cov=src --cov-report=html
```

---

## 12. 待决策项

| 问题 | 决策结果 / 待选方案 | 优先级 |
|------|---------------------|--------|
| ~~前端技术栈~~ | ✅ 已定：微信小程序 + Flutter + Web 管理后台 | — |
| 文件存储 | 本地卷 vs 阿里云 OSS vs MinIO | P1 |
| LLM 供应商 | OpenAI GPT-4o vs 阿里云 Qwen（成本更低） | P0 |
| 推送通知 | 微信服务通知（已选）+ Firebase FCM（iOS/Android） | P1 |
| 部署平台 | 阿里云 ECS vs 腾讯云 vs 自建 | P2 |
