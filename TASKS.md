# LifePilot - 家庭健康管理 AI 项目任务清单

> 创建日期：2026-04-24  
> 最后更新：2026-05-01（T017 环境健康监控：PM2.5/CO₂/温湿度传感器 + 健康阈值耦警 + 小米/Home Assistant 接入 + LLM 建议，52 个测试全部通过）  
> 目标：用 AI 技术实现一套家庭健康管理系统

---

## ⚡ 开发工作流规则

**每次完成任意 Task 后，必须执行以下三步再提交：**

```bash
# 1. 更新 TASKS.md   → 标记完成项、更新进度百分比
# 2. 更新 README.md  → 反映对外可见的功能/使用变化
# 3. 更新 doc/architecture.md → 记录设计决策变更
# 4. 补全测试
# 5. 同步README_EN.md
git add .
git commit -m "feat/fix/docs: 描述"
git push
```

---

## 进度总览

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| 阶段零：部署基础设施 | ✅ 已完成 | 100% |
| 阶段一：基础架构搭建 | ✅ 已完成 | 100% |
| 阶段二：核心健康监测 | 🔄 进行中 | 80%（T005/T006/T007/T008 完成，T009+ 属阶段三）|
| 阶段三：智能问诊助手 | ✅ 已完成 | 100%（5/5 任务完成）|
| 阶段四：生活方式干预 | ✅ 已完成 | 100%（3/3 任务全部完成）|
| 阶段五：智能家居联动 | 🔄 进行中 | 25%（T017 环境监控完成）|
| 阶段六：报告与就医辅助 | 🔄 进行中 | 75%（T018/T019/T020 完成，PDF/定时任务延后）|
| 阶段七：前端与产品化 | ⬜ 未开始 | 0% |

---

## 阶段零：部署基础设施 ✅

> 完成于 2026-04-24

### T000 - Docker Compose 部署环境（已完成）
- [x] 编写多阶段 `Dockerfile`（`development` / `production` 两个 target）
- [x] 编写 `docker-compose.yml`（生产环境：API + PostgreSQL + InfluxDB + Qdrant + Redis + Celery Worker + Nginx）
- [x] 编写 `docker-compose.dev.yml`（开发覆盖层，挂载源码实现热更新）
- [x] 编写 `Makefile`（`make dev` / `make prod` / `make logs` / `make db-migrate` 等快捷命令）
- [x] 创建 `.env.example` 环境变量模板
- [x] 配置 `.gitignore`（排除 `.env`、数据卷目录、缓存文件）
- [x] 初始化项目目录结构（`src/`, `tests/`, `scripts/`, `docker/`, `data/`）
- [x] 创建 FastAPI 入口 `src/main.py`（含健康检查、CORS、lifespan 管理）
- [x] 创建 `src/core/config.py`（pydantic-settings 统一配置管理）
- [x] 创建 `src/core/logging.py`（structlog 结构化日志）
- [x] 创建 `src/workers/celery_app.py`（Celery 异步任务框架）
- [x] 创建 `requirements.txt`（FastAPI / LangChain / PaddleOCR / Celery 等依赖）
- [x] 创建 `docker/postgres/init.sql`（uuid-ossp / pgcrypto 扩展初始化）

**热更新说明**：`docker-compose.dev.yml` 将 `./src` 以 volume 挂载到容器，uvicorn `--reload --reload-dir /app/src` 监测文件变更自动重启，worker 通过 `watchfiles` 实现同等效果。

```bash
# 一键启动开发环境（含热更新）
cp .env.example .env.dev  # 首次：配置环境变量
make dev
```

---

## 阶段一：基础架构搭建

### T001 - 项目初始化 ✅
- [x] 初始化 Python 项目结构（`src/`, `tests/`, `docker/`, `data/`）
- [x] 建立 `.gitignore`
- [x] 编写 `README.md`（快速开始 / 功能概览 / 项目结构 / 常用命令）

> ℹ️ 本地虚拟环境无需配置——开发依赖完全由 Docker 容器管理。若 IDE 需要类型提示，可在本地执行一次 `pip install -r requirements.txt -t .venv/` 供静态分析使用，无需激活。

### T002 - 数据库设计
- [x] 设计家庭成员健康档案数据模型（`Member`, `HealthRecord`, `Medication`）
- [x] 搭建 PostgreSQL（已配置 docker-compose）
- [x] 搭建 InfluxDB（已配置 docker-compose）
- [x] 搭建 Qdrant 向量数据库（已配置 docker-compose）
- [x] 用 SQLAlchemy 编写 ORM 模型（`src/models/`）
  - `Family` / `Member`（角色：admin/adult/elder/child）
  - `HealthRecord`（血压/血糖/心率/体重等 10 种指标）
  - `SymptomLog`（症状日记，含 NLP 结果和就医建议等级）
  - `Medication` / `MedicationReminder` / `AdherenceLog`（用药依从性）
  - `LabReport`（检验单，含 OCR 原文和 LLM 解读字段）
- [x] 配置 Alembic 异步迁移框架（`alembic init -t async`，env.py 接入项目 metadata）
- [ ] 编写 Alembic 初始 migration（需数据库运行后执行：`make db-migrate`）
- [x] 创建 `src/core/database.py`（异步 engine / session / `get_db` 依赖）

### T003 - 认证与多用户支持 ✅
- [x] 实现家庭账户注册 / 登录（JWT）
  - `POST /api/v1/auth/register` 注册家庭账户 + 创建 admin 成员
  - `POST /api/v1/auth/login` 邮箱密码登录，返回 access + refresh token
  - `POST /api/v1/auth/refresh` 无感刷新 token
  - `GET  /api/v1/auth/me` 当前登录成员信息
- [x] 实现家庭成员子账户管理（家长/老人/儿童角色区分）
  - `GET    /api/v1/auth/family` 家庭信息 + 成员列表（仅 admin）
  - `POST   /api/v1/auth/family/members` 添加成员（仅 admin）
  - `PATCH  /api/v1/auth/family/members/{id}` 更新成员信息（自己或 admin）
  - `DELETE /api/v1/auth/family/members/{id}` 删除成员（仅 admin）
- [x] 设置成员级别的访问权限控制
  - `get_current_member` 依赖：从 Bearer token 解析当前成员
  - `get_current_admin` 依赖：要求 admin 角色
  - `require_same_family()` 工具：防止跨家庭越权访问

### T-test - 测试框架搭建 ✅
> 完成于 2026-04-24

- [x] 搭建 pytest + pytest-asyncio 异步测试框架（`asyncio_mode=auto`）
- [x] 配置 SQLite in-memory 测试数据库（aiosqlite，每用例事务回滚隔离）
- [x] 用 httpx `AsyncClient` + `ASGITransport` 进行无服务器集成测试
- [x] 创建 `tests/conftest.py`（engine/db_session/client/registered_family/auth_headers fixtures）
- [x] 编写 `tests/test_security.py`（密码哈希 + JWT 单元测试，11 个用例）
- [x] 编写 `tests/test_auth.py`（注册/登录/refresh/me 集成测试，14 个用例）
- [x] 编写 `tests/test_members.py`（家庭成员 CRUD 集成测试，15 个用例）
- [x] 编写 `tests/test_system.py`（健康检查，2 个用例）
- [x] 搭建 selenium E2E 测试框架（Chrome headless，`tests/e2e/`）
- [x] 编写 `tests/e2e/test_web_admin.py`（Web Admin 登录/Dashboard E2E 测试）
- [x] 配置 `requirements-test.txt` + `pytest.ini` 
- [x] 创建 `.env.test`（隔离测试环境变量）
- [x] 修复 Python 3.9 兼容性：`Mapped[X | None]` → `Mapped[Optional[X]]`（ORM 模型层）
- [x] 修复 SQLAlchemy async 懒加载问题：改用 `selectinload` 急加载关联关系
- [x] 降级 `bcrypt==3.2.2` 以兼容 `passlib==1.7.4`
- [x] **44/44 测试全部通过** ✅

```bash
# 运行单元 + 集成测试
make test-local
# 或：python -m pytest tests/ --ignore=tests/e2e -v
```

---

## 阶段二：核心健康监测

### T004 - 健康数据录入模块 ✅
> 完成于 2026-04-24

- [x] 开发手动录入 API（血压、血糖、体重、心率等指标）
  - `POST   /api/v1/health/{member_id}/records` 单条录入（含异常值验证）
  - `POST   /api/v1/health/{member_id}/records/batch` 批量录入（JSON，最多 500 条）
  - `POST   /api/v1/health/{member_id}/records/import-csv` CSV 批量导入历史数据
  - `GET    /api/v1/health/{member_id}/records` 记录列表（支持按类型/时间过滤 + 分页）
  - `DELETE /api/v1/health/{member_id}/records/{record_id}` 删除单条记录
  - `GET    /api/v1/health/{member_id}/summary` 各指标统计摘要（最新值/最大最小/均值）
- [x] 数据合法性校验与异常值过滤（每种指标的合理值域）
- [x] 自动填充单位（mmHg / bpm / mmol/L / kg / cm / °C / % 等）
- [x] 权限控制（仅本人或 admin 可访问成员数据）
- [x] 编写 17 个集成测试（全部通过）

支持的 10 种指标类型：
| 指标 | MetricType | 单位 | 正常范围 |
|------|-----------|------|---------|
| 收缩压 | blood_pressure_sys | mmHg | 50–300 |
| 舒张压 | blood_pressure_dia | mmHg | 30–200 |
| 心率 | heart_rate | bpm | 20–300 |
| 血糖 | blood_glucose | mmol/L | 1–50 |
| 体重 | weight | kg | 1–500 |
| 身高 | height | cm | 20–300 |
| 体温 | body_temperature | °C | 30–45 |
| 血氧 | spo2 | % | 50–100 |
| 步数 | steps | 步 | 0–200000 |
| 睡眠 | sleep_hours | h | 0–24 |

- [ ] 集成可穿戴设备数据接入（Apple Health / Mi Band / Fitbit API）— 延后至 T005

### T005 - 慢病趋势预测 ✅
> 完成于 2026-05-01

- [x] 个性化健康阈值规则引擎
  - per-member 可配置每种指标的 warning/danger 上下限（upsert）
  - 系统内置 6 种指标默认阈值（血压/心率/血糖/体温/血氧）
  - 自定义阈值优先级 > 系统默认值；支持禁用
- [x] 健康数据录入时自动检测并创建告警
  - 1 小时冷却期（同指标同方向不重复触发）
  - 分级：INFO < WARNING < DANGER（优先显示最严重等级）
- [x] 告警管理：列表/详情/确认（acknowledge）/删除
  - 多维度过滤：severity / status / metric_type
  - 确认告警支持附加备注（llm_advice 字段）
- [x] 趋势分析（最小二乘线性回归）
  - 计算近 N 条记录的均值/最大/最小/标准差/每日斜率
  - 趋势方向判定：rising / falling / stable / fluctuating
  - LLM 生成通俗趋势解读（失败时静默降级为规则描述）
  - 趋势快照持久化（history 可查询）
- [x] 11 个 REST 端点：默认阈值查看 / 阈值 CRUD / 告警 CRUD+确认 / 趋势分析列表最新
- [x] 43 个集成 + 单元测试（LLM 全部 mock），总计 350/350 通过
- [x] Alembic 迁移：`0010_alerts`（health_thresholds / health_alerts / health_trend_snapshots）

```
GET  /api/v1/alerts/{member_id}/thresholds/defaults    查看系统内置默认阈值
POST /api/v1/alerts/{member_id}/thresholds             设置/更新个性化阈值
GET  /api/v1/alerts/{member_id}/thresholds             阈值列表
DEL  /api/v1/alerts/{member_id}/thresholds/{metric}    删除阈值（恢复默认）
GET  /api/v1/alerts/{member_id}/alerts                 告警列表（支持多维过滤）
GET  /api/v1/alerts/{member_id}/alerts/{id}            告警详情
PATCH /api/v1/alerts/{member_id}/alerts/{id}/acknowledge  确认告警
DEL  /api/v1/alerts/{member_id}/alerts/{id}            删除告警
POST /api/v1/alerts/{member_id}/trends                 生成趋势快照（LLM 解读可选）
GET  /api/v1/alerts/{member_id}/trends                 趋势快照列表
GET  /api/v1/alerts/{member_id}/trends/latest          获取某指标最新快照
```

### T006 - 睡眠质量分析 ✅
> 完成于 2026-05-01

- [x] 睡眠记录手动录入（支持入睡/起床时间，自动计算总时长）
  - 支持设备导入：manual / mi_band / apple_health / fitbit
  - 可选字段：深睡眠/浅睡眠/REM/清醒时长、觉醒次数、SpO₂
- [x] 多维综合评分算法（0-100）
  - 时长因子 35%：成人 7-9h 满分，过短/过长线性扣分
  - 深睡眠因子 25%：深睡占比 ≥ 20% 满分
  - REM 因子 20%：REM 占比 ≥ 20% 满分
  - 连续性因子 10%：觉醒次数 0-1 满分
  - 血氧因子 10%：SpO₂ min ≥ 95% 满分
- [x] 睡眠质量等级：poor（<40）/ fair（40-59）/ good（60-79）/ excellent（≥80）
- [x] 呼吸暂停风险检测：SpO₂ min < 90% → high，< 94% → moderate，否则 low
- [x] 近 N 天趋势汇总（均值/连续低质量次数/高风险次数/最低血氧）
- [x] LLM 生成个性化睡眠改善建议（失败时静默降级为规则建议）
- [x] 5 个 REST 端点：录入（自动评分+建议）/ 列表过滤 / 详情 / 删除 / 趋势汇总
- [x] 25 个集成 + 单元测试（LLM 全部 mock），总计 375/375 通过
- [x] Alembic 迁移：`0011_sleep`（sleep_records）

```
POST   /api/v1/sleep/{member_id}/records          录入睡眠数据（自动评分 + LLM 建议）
GET    /api/v1/sleep/{member_id}/records          记录列表（可按 quality 过滤 + 分页）
GET    /api/v1/sleep/{member_id}/records/{id}     记录详情
DELETE /api/v1/sleep/{member_id}/records/{id}     删除记录
GET    /api/v1/sleep/{member_id}/summary          近 N 天趋势汇总统计
```

### T007 - 児童生长发育评估 ✅
> 完成于 2026-05-01

- [x] 集成 WHO 生长标准数据（LMS 参数内置，0-60 月龄，男/女分开）
- [x] LMS 方法计算身高/体重百分位及 Z-score
- [x] BMI 计算（月龄 ≥ 24 月时评估）
- [x] 7 级 GrowthCategory 分级（P1/P3/P15/P85/P97/P99 分界）
- [x] 24 条系统预设发育里程碑（AAP/WHO 参考，大运动/精细动作/语言/认知/社会情感 5类）
- [x] 里程碑达成记录（记录达成日期和实际月龄）
- [x] LLM 生成综合生长评估报告（失败时静默降级为规则建议）
- [x] 11 个 REST 端点：生长记录 CRUD / 里程碑初始化+CRUD+达成 / 生长概览
- [x] 32 个集成 + 单元测试（LLM 全部 mock），总计 407/407 通过
- [x] Alembic 迁移：`0012_growth`（growth_records / development_milestones）

```
POST   /api/v1/growth/{member_id}/records              录入身高/体重（WHO 百分位 + LLM 评估）
GET    /api/v1/growth/{member_id}/records              生长记录列表
GET    /api/v1/growth/{member_id}/records/{id}         记录详情
DELETE /api/v1/growth/{member_id}/records/{id}         删除记录
POST   /api/v1/growth/{member_id}/milestones/init      初始化预设里程碑（24 条，幂等）
POST   /api/v1/growth/{member_id}/milestones           添加自定义里程碑
GET    /api/v1/growth/{member_id}/milestones           里程碑列表（可按类型/状态过滤）
PATCH  /api/v1/growth/{member_id}/milestones/{id}/achieve 标记已达成
DELETE /api/v1/growth/{member_id}/milestones/{id}      删除自定义里程碑
GET    /api/v1/growth/{member_id}/summary              生长概览（最新记录+里程碑统计）
```

### T008 - 老人跌倒风险评估 ✅
> 完成于 2026-05-01

- [x] 定义跌倒风险评估指标（改进版 Morse Fall Scale + Hendrich II 合并，11 项 boolean 维度）
- [x] 开发风险评分模型（总分 0-28，LOW/MODERATE/HIGH/VERY_HIGH，年龄调整 +1/+2）
  - has_fall_history(+3) / has_osteoporosis(+2) / has_neurological_disease(+3)
  - uses_sedatives(+2) / has_gait_disorder(+3) / uses_walking_aid(+2)
  - has_vision_impairment(+2) / has_weakness_or_balance_issue(+3)
  - lives_alone(+2) / frequent_nocturia(+2) / has_urge_incontinence(+2)
- [x] 实现长时间不活动检测（查询最后 steps/heart_rate 记录时间，超阈值创建 InactivityLog）
  - 30 分钟去重窗口防止重复告警
  - 可配置 threshold_hours（1-24h，默认 4h）
- [x] 紧急联系人告警消息生成（InactivityLog.alert_message）
- [x] LLM 生成个性化干预建议（失败时静默降级为规则建议）
- [x] 8 个 REST 端点：评估 CRUD（含最新/列表/过滤）+ 不活动检测+列表 + 概览
- [x] 28 个集成 + 单元测试（LLM 全部 mock），总计 435/435 通过
- [x] Alembic 迁移：`0013_fall_risk`（fall_risk_assessments / inactivity_logs）

```
POST   /api/v1/fall-risk/{member_id}/assessments           提交问卷（自动评分 + LLM 建议）
GET    /api/v1/fall-risk/{member_id}/assessments           评估列表（可按 risk_level 过滤）
GET    /api/v1/fall-risk/{member_id}/assessments/latest    最新评估
GET    /api/v1/fall-risk/{member_id}/assessments/{id}      评估详情
DELETE /api/v1/fall-risk/{member_id}/assessments/{id}      删除评估
POST   /api/v1/fall-risk/{member_id}/inactivity/check      触发不活动检测
GET    /api/v1/fall-risk/{member_id}/inactivity            不活动记录列表
GET    /api/v1/fall-risk/{member_id}/summary               综合概览
```

---

## 阶段三：智能问诊助手（RAG）

### T009 - 健康知识库构建 ✅
> 完成于 2026-04-24；v2 升级于 2026-04-24

- [x] 文档清洗与分块（token-based chunking，默认 512 token / 64 重叠）
- [x] **表格感知分块**（Markdown 表格整体保留，跨行不截断）
- [x] **本地 bge-m3 推理**（`USE_LOCAL_EMBEDDING=true`）+ OpenAI API 双模式
- [x] **Redis Embedding 缓存**（7 天 TTL，避免重复推理）
- [x] 向量存入 Qdrant（COSINE 距离，支持 upsert 防重复）
- [x] **三类知识分区**：`disease` / `red_flag` / `triage`，供 Agentic 路由使用
- [x] **CrossEncoder Reranker**（`USE_RERANKER=true`，ms-marco-MiniLM-L-6-v2）
- [x] **Redis 查询缓存**（5 分钟 TTL）
- [x] 并行多类别检索（`search_multi_category`）
- [x] 按来源批量删除（用于知识库更新）
- [x] 统计信息接口

```bash
# 管理员摄入文档（通过 API）
POST /api/v1/chat/knowledge
{"content": "...", "source": "丁香医生", "title": "高血压基础", "category": "内科"}

# 查看知识库统计
GET /api/v1/chat/knowledge/stats
```

### T010 - 家庭健康 RAG 问答助手 ✅
> 完成于 2026-04-24；v2 升级于 2026-04-24（参考 FamilyHealthyAgent 架构）

- [x] **Agentic 三工具 RAG**（并行检索 + 路由决策）
  - 工具1 `check_red_flag`：危险症状库，score > 0.72 直接触发急诊警告
  - 工具2 `get_triage`：分诊导诊（"挂什么科" 等关键词触发）
  - 工具3 `search_disease`：通用疾病/药物知识（默认）
- [x] **多成员记忆隔离**（`_member_sessions[member_id]`，各成员独立对话历史）
- [x] **成员健康档案注入**（从 DB 查询年龄/指标/用药，注入 system prompt）
- [x] **老人/儿童个体化约束**（role=elder/child 时调整语言风格和注意事项）
- [x] 多轮对话（ChatSession，最多保留 10 轮历史）
- [x] 流式输出（SSE，`POST /api/v1/chat/stream`）
- [x] 安全过滤（拒绝敏感词及非健康类问题）
- [x] 会话管理（`DELETE /sessions/me` 清除当前成员记忆）
- [x] 知识来源引用（返回 sources 列表）
- [x] 21 个测试全部通过（单元 12 + 集成 9）

```
POST /api/v1/chat/          同步问答
POST /api/v1/chat/stream    流式 SSE 问答
DELETE /api/v1/chat/sessions/{id}  清空会话
```

### T011 - 症状日记 NLP 分析 ✅
> 完成于 2026-04-24

- [x] 症状日记录入 API（用户自由描述，可指定发生时间）
- [x] LLM NLP 症状结构化提取（名称/部位/程度/持续时间/性质）
- [x] 严重度评分 1-10 + 就医建议等级（self_care/monitor/visit_soon/emergency）
- [x] 生成通信的症状总结（含免责声明）
- [x] LLM 失败时静默降级，原始文本正常保存
- [x] 4 个 REST 端点：第录并分析 / 列表 / 详情 / 删除
- [x] 支持按 advice_level 过滤列表
- [x] 20 个集成 + 单元测试（LLM 全部 mock），总计 187/187 通过
- [x] API 版本升至 v0.9.0
- [ ] 语音转文字（延后至前端实现）

### T012 - 检验单 AI 解读 ✅
- [x] 集成 OCR 引擎（PaddleOCR / Tesseract 均支持，自动降级）
- [x] LLM 解读血常规、生化、尿常规等 8 类报告（JSON 结构化输出）
- [x] 标注异常项（方向/临床提示）并用通俗语言解释，附免责声明
- [x] 历史报告异常项趋势对比（`GET /compare` 接口）
- [x] PDF / 图片 / TXT 上传接口（≤20 MB，文件类型校验）
- [x] 20 个集成 + 单元测试（OCR & OpenAI 全部 mock）

### T013 - 皮肤/伤口照片辅助分析 ✅
> 完成于 2026-04-27

- [x] 接入多模态模型（三后端可选）
  - `openai`：GPT-4o / 任何 OpenAI 兼容供应商（DeepSeek-VL2 / Moonshot / Qwen VL API / 智谱 GLM-4V / Azure OpenAI）
  - `ollama`：本地 Ollama 服务（Qwen2-VL:7b / LLaVA 等），OpenAI 兼容接口
  - `local`：transformers 本地推理（Qwen2-VL-Instruct），线程池执行，不阻塞事件循环
- [x] 专用 `SKIN_VISION_API_KEY` / `SKIN_VISION_BASE_URL`（空时回退全局 OpenAI 配置）
- [x] 图片上传与预处理（JPEG/PNG/WEBP/BMP，≤10 MB，base64 编码传模型）
- [x] LLM 结构化输出：findings / possible_conditions / care_advice / summary
- [x] 输出结果等级：normal / attention / visit_soon / emergency
- [x] 图片本地存储（`data/skin_images/`）+ 审计字段（使用模型记录）
- [x] LLM 失败静默降级（图片路径保留，分析标 attention）
- [x] 免责声明自动附加
- [x] 4 个 REST 端点：上传分析 / 列表 / 详情 / 删除
- [x] 23 个集成 + 单元测试（LLM 全部 mock），总计 255/255 通过
- [x] Alembic 迁移：`0007_skin_analyses`

```
POST /api/v1/skin/{member_id}/analyze       上传照片 + AI 辅助分析
GET  /api/v1/skin/{member_id}/analyses      历史分析列表（可按 result 过滤）
GET  /api/v1/skin/{member_id}/analyses/{id} 详情
DELETE /api/v1/skin/{member_id}/analyses/{id} 删除
```

---

## 阶段四：生活方式干预

### T014 - 个性化营养规划 ✅
> 完成于 2026-04-27

- [x] 食物营养素数据库（模型 + 模糊搜索 API）
- [x] 基于健康档案生成营养目标
  - Harris-Benedict 公式计算 BMR ＋活动系数（TDEE）作为算法基准
  - LLM 个性化调整（饮食类型 / 过敏原 / 禁忌 / 用药考虑）
  - LLM 失败时静默降级为公式默认值
- [x] 支持 9 种饮食类型（普通/素食/纯素/低碳/低盐/低糖/低脂/高蛋白/无麦质）
- [x] LLM 生成个性化每周食谱（7 天 × 3 餐 + 加餐，符合中国饮食习惯）
- [x] 饮食日志录入（自由文本）+ LLM 营养素估算（卡路里/蛋白质/脂肪/碳水化合物）+ 健康反馈
- [x] 日摄入汇总表（各餐汇总当日全部营养素）
- [x] upsert 营养目标（重复 POST 更新而不重复）
- [x] 8 个 REST 端点：食物搜索 / 目标生成获取 / 食谱列表详情删除 / 日志列表详情删除 / 日摄入汇总
- [x] 32 个集成 + 单元测试（LLM 全部 mock），总计 269/269 通过
- [x] Alembic 迁移：`0008_nutrition`（food_items / nutrition_goals / meal_plans / diet_logs）

```
GET  /api/v1/nutrition/foods                              食物搜索
POST /api/v1/nutrition/{member_id}/goal                   创建/更新营养目标
GET  /api/v1/nutrition/{member_id}/goal                   获取营养目标
POST /api/v1/nutrition/{member_id}/meal-plans             生成本周食谱
GET  /api/v1/nutrition/{member_id}/meal-plans             食谱列表
GET  /api/v1/nutrition/{member_id}/meal-plans/{id}        食谱详情
DELETE /api/v1/nutrition/{member_id}/meal-plans/{id}      删除食谱
POST /api/v1/nutrition/{member_id}/diet-logs              记录饮食
GET  /api/v1/nutrition/{member_id}/diet-logs              日志列表
GET  /api/v1/nutrition/{member_id}/diet-logs/summary      日摄入汇总
DELETE /api/v1/nutrition/{member_id}/diet-logs/{id}       删除日志
```

### T015 - 运动方案生成与追踪 ✅
> 完成于 2026-05-01

- [x] 体能评估问卷设计（fitness_level / primary_goal / available_days / limitations / equipment）
  - upsert 机制：重复 POST 更新已有评估而不创建新记录
  - 支持 5 种体能水平（久坐/初级/中级/高级/专业）
  - 支持 6 种运动目标（减脂/增肌/提升心肺/维持健康/康复/柔韧性）
- [x] LLM 生成个性化运动计划（类型/强度/频率）
  - 7 天计划 JSON（每天含：休息/训练主题/具体动作/组数/热量估算/技巧提示）
  - LLM 失败时静默降级为规则生成的基础有氧计划
  - 支持 7 种运动类型（有氧/力量/柔韧/HIIT/球类/健步走/游泳）
  - 新计划生成时自动将旧计划标记为 is_active=False
- [x] 运动数据追踪（步数/心率/卡路里）
  - METs 公式估算热量消耗（cardio: 7.0 / HIIT: 12.0 / walking: 3.5 等）
  - 记录状态：completed / skipped / partial
  - 心率上/下限校验（30-250 bpm）
  - LLM 分析运动日志并生成个性化恢复建议
- [x] 每周汇总统计（完成次数/总时长/总热量/平均心率）
- [x] 活跃计划快速获取接口（`GET /plans/active`）
- [x] 8 个 REST 端点：体能评估创建获取 / 计划生成列表获取 / 日志 CRUD / 每周汇总
- [x] 38 个集成 + 单元测试（LLM 全部 mock），总计 307/307 通过
- [x] Alembic 迁移：`0009_fitness`（fitness_assessments / exercise_plans / workout_logs）

```
POST /api/v1/fitness/{member_id}/assessment         创建/更新体能评估问卷
GET  /api/v1/fitness/{member_id}/assessment         获取体能评估
POST /api/v1/fitness/{member_id}/plans              LLM 生成本周运动计划
GET  /api/v1/fitness/{member_id}/plans              计划列表
GET  /api/v1/fitness/{member_id}/plans/active       当前活跃计划
POST /api/v1/fitness/{member_id}/logs               记录一次运动日志
GET  /api/v1/fitness/{member_id}/logs               日志列表（支持日期过滤）
GET  /api/v1/fitness/{member_id}/logs/{id}          日志详情
DELETE /api/v1/fitness/{member_id}/logs/{id}        删除日志
GET  /api/v1/fitness/{member_id}/summary/weekly     每周运动汇总统计
```

### T016 - 心理健康筛查 ✅
> 完成于 2026-04-24

- [x] 设计情绪日记录入（文字 + 情绪标签，LLM 自动 NLP 分析）
- [x] NLP 情绪分析（情感倾向、mood_score 1-10、情绪关键词提取、LLM 失败时静默降级）
- [x] PHQ-9 抑郁自评量表集成（9 题，总分 0-27，规则评分）
- [x] GAD-7 广泛性焦虑量表集成（7 题，总分 0-21，规则评分）
- [x] 风险等级自动判定：low / moderate / high / crisis（取 PHQ-9 / GAD-7 / NLP 三者最高级别）
- [x] 风险预警：crisis 等级自动附带危机热线 / 急救电话
- [x] 推荐心理干预资源（随风险等级升级：冥想 App / 自助书单 / 心理咨询 / 危机热线）
- [x] 6 个 REST 端点：题库查询 / 情绪日记 / 量表评估 / 列表 / 详情 / 删除
- [x] 27 个集成 + 单元测试（LLM 全部 mock），总计 214/214 通过
- [x] API 版本升至 v1.0.0

---

## 阶段五：智能家居联动

### T017 - 环境健康监控 ✅
> 完成于 2026-05-01

- [x] 集成传感器数据接入（PM2.5、CO₂、温度、湿度、VOC、噪音、CO，共 8 种指标）
  - 手动录入（manual）/ 小米传感器 Webhook（xiaomi）/ Home Assistant Webhook三类来源
  - MiHome lumi.sensor_ht 属性映射适配器
  - Home Assistant entity_id 关键词匹配适配器
- [x] 建立环境健康阈值规则（WHO 2021 / 国标 GB/T18883）
  - warning / danger 双级阈値，温湿度支持高値+低値双向检测
  - 录入时自动 is_alert / alert_level 标注
- [x] 综合空气质量等级（EXCELLENT/GOOD/MODERATE/POOR/VERY_POOR/HAZARDOUS）
  - 取各指标最差等级作为综合结果
- [x] LLM 生成个性化环境改善建议，失败时静默降级为规则建议
- [x] 10 个 REST 端点：单条/批量录入 / 列表过滤 / 详情/删除 / 综合摘要 / LLM建议+历史 / Webhook 小米+HA
- [x] 52 个集成 + 单元测试（LLM 全部 mock），总计 487/487 通过
- [x] Alembic 迁移：`0014_environment`（environment_records / environment_advice）

```
POST   /api/v1/environment/{member_id}/records                    手动录入一条环境指标
POST   /api/v1/environment/{member_id}/records/batch              批量录入（最多 200 条）
GET    /api/v1/environment/{member_id}/records                    记录列表（可按指标类型/位置/时间窗口/告警过滤）
GET    /api/v1/environment/{member_id}/records/{id}               单条详情
DELETE /api/v1/environment/{member_id}/records/{id}               删除记录
GET    /api/v1/environment/{member_id}/summary                   当前室内环境综合摘要
POST   /api/v1/environment/{member_id}/advice                    生成 LLM 环境改善建议
GET    /api/v1/environment/{member_id}/advice                    历史 LLM 建议列表
POST   /api/v1/environment/{member_id}/webhook/xiaomi            小米传感器 Webhook 接入
POST   /api/v1/environment/{member_id}/webhook/home-assistant    Home Assistant Webhook 接入
```

---

## 阶段六：报告与就医辅助

### T018 - 家庭健康周报/月报 ✅
> 完成于 2026-04-24

- [x] 聚合周期内健康指标统计（avg/min/max/count/趋势，按 MetricType 分组）
- [x] 汇总用药依从性（每种药物的依从率计算）
- [x] 提取异常事件（超出正常值域的记录列表）
- [x] LLM 自动生成自然语言总结（失败时静默降级，不阻塞报告保存）
- [x] 4 个 REST 端点：生成 / 列表 / 详情 / 删除
- [x] 21 个集成 + 单元测试（LLM 全部 mock），总计 146/146 通过
- [x] API 版本升至 v0.7.0
- [ ] 定时任务触发（Celery Beat，延后至基础设施完善后实现）
- [ ] PDF 导出 / 分享链接（延后至前端完成后实现）

### T019 - 就医准备助手 ✅
> 完成于 2026-04-24

- [x] 就医前问卷：主诉、持续时间、加重/缓解因素、既往史（用户自填）
- [x] 自动从 DB 聚合当前活跃用药清单
- [x] 自动从 DB 聚合近期健康指标摘要（可配置回查天数，默认 30 天）
- [x] 自动从 DB 聚合近 90 天检验单异常项
- [x] LLM 生成结构化就诊摘要（支持中文/英文/双语）
- [x] LLM 调用失败时静默降级，快照数据正常保存
- [x] 4 个 REST 端点：生成 / 列表 / 详情 / 删除
- [x] 21 个集成 + 单元测试（LLM 全部 mock），总计 167/167 通过
- [x] API 版本升至 v0.8.0
- [ ] PDF 导出（延后至前端完成后实现）

### T020 - 用药管理与提醒 ✅
- [x] 设置用药方案（名称/剂量/频次/起止日期），LLM 自动生成通俗说明
- [x] 设置个性化服药提醒时间（HH:MM 格式，支持多时段）
- [x] 记录用药依从性（taken/missed/delayed/skipped）
- [x] 统计依从性（按时服药率、各状态计数）
- [x] LLM 多药物相互作用风险检查（risk_level: none/low/moderate/high/critical）
- [x] LLM 调用失败时静默降级，不阻塞业务
- [x] 23 个集成 + 单元测试（LLM 全部 mock）

---

## 阶段七：前端与产品化

> 前端选型已确定：三端并行
> - **微信小程序**：日常用户端（国内用户无需下载 App，触达成本最低）
> - **Flutter**：移动端 App（一套代码跨 iOS/Android，适合老人大字体 UI）
> - **Web 管理后台**（React + Ant Design）：家庭健康数据总览、成员管理、异常预警查看

### T021 - 微信小程序（用户端）
- [ ] 初始化小程序项目（uni-app 框架，支持微信 + H5 双端发布）
- [ ] 登录 / 家庭绑定界面
- [ ] 健康数据快捷录入（血压/血糖/体重）
- [ ] 检验单拍照上传与 AI 解读展示
- [ ] 健康问诊聊天界面（RAG）
- [ ] 用药提醒推送通知（微信服务通知）
- [ ] 小程序首页健康概览卡片

### T022 - Flutter App（移动端）
- [ ] 初始化 Flutter 项目（iOS + Android）
- [ ] 适配老人友好 UI（大字体、高对比度、简化导航）
- [ ] 健康指标可视化图表（血压/血糖趋势曲线）
- [ ] 成员健康档案页
- [ ] 简体 / 英文双语言支持
- [ ] 离线山地基本功能（本地数据缓存）

### T023 - Web 管理后台（新增）
- [ ] 技术选型：React 18 + Ant Design Pro + ECharts
- [ ] 家庭全员健康总览 Dashboard
  - 各成员关键指标卡片（血压/血糖/用药状态）
  - 异常预警消息中心
  - 近 30 天健康趋势折线图
- [ ] 家庭成员管理页（增/改/删、角色配置）
- [ ] 检验单历史记录列表 + 详情页
- [ ] 周报/月报在线查看 + PDF 导出
- [ ] 用药依从性统计图表
- [ ] Docker Compose 集成部署（Nginx 服务前端静态资源）

### T024 - API 服务化与部署
- [ ] 编写 OpenAPI 文档（已通过 FastAPI 自动生成）
- [ ] 实现限流与安全防护（Rate Limiting、输入校验）
- [ ] 部署到云服务（阶段一：阿里云 ECS / 腾讯云）

---
### T025 - 免责
- [ ] 输出需要免责声明，结论仅供参考，需要请及时线下就医

## 优先级总览

| 优先级 | 任务 | 价值 | 难度 | 状态 |
|--------|------|------|------|------|
| ✅ 完成 | T000 Docker 部署基础设施 | 高 | 中 | 已完成 |
| ✅ 完成 | T001 基础架构 | 高 | 低 | 已完成 |
| P0 🔴 | T002 数据库 ORM 模型 | 高 | 中 | ✅ 已完成 |
| P0 🔴 | T003 认证与多用户 | 高 | 中 | ✅ 已完成 |
| ✅ 完成 | T-test 测试框架 | 高 | 中 | ✅ 已完成 (61/61) |
| P0 🔴 | T004 健康数据录入 | 高 | 低 | ✅ 已完成 |
| P0 🔴 | T010 RAG 问答助手 | 高 | 中 | ✅ 已完成 |
| P0 🔴 | T012 检验单解读 | 极高 | 中 | ✅ 已完成 |
| P0 🔴 | T011 症状日记 NLP | 高 | 中 | ✅ 已完成 |
| P1 🟡 | T019 就医准备助手 | 高 | 中 | ✅ 已完成 |
| P1 🟡 | T005 慢病趋势预测 | 高 | 高 | ⬜ 未开始 |
| P1 🟡 | T018 健康周报 | 中 | 低 | ✅ 已完成 |
| P1 🟡 | T020 用药管理 | 高 | 中 | ✅ 已完成 |
| P1 🟡 | T021 微信小程序 | 高 | 中 | ⬜ 未开始 |
| P1 🟡 | T022 Flutter App | 高 | 高 | ⬜ 未开始 |
| P1 🟡 | T023 Web 管理后台 | 高 | 中 | ⬜ 未开始 |
| P2 🟢 | T006 睡眠分析 | 中 | 中 | ✅ 已完成 |
| P2 🟢 | T007 儿童生长发育评估 | 中 | 中 | ✅ 已完成 |
| P2 🟢 | T013 照片辅助分析 | 中 | 中 | ⬜ 未开始 |
| P2 🟢 | T016 心理健康筛查 | 中 | 中 | ✅ 已完成 |
| P3 ⚪ | T008 老人跌倒检测 | 中 | 高 | ⬜ 未开始 |
| P3 ⚪ | T017 智能家居联动 | 低 | 高 | ⬜ 未开始 |
| P3 ⚪ | T024 云部署 | 中 | 中 | ⬜ 未开始 |

---

## 推荐起步路径

```
✅ T000 → ✅ T001 → ✅ T002 → ✅ T003 → ✅ T004 → T009 → T010 → T012 → T020 → T018
```

> **最小可行产品（MVP）**：健康数据录入 + 检验单 AI 解读 + RAG 问答助手
