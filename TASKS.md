# LifePilot - 家庭健康管理 AI 项目任务清单

> 创建日期：2026-04-24  
> 最后更新：2026-04-24（T016 心理健康筛查：PHQ-9/GAD-7 量表自动评分 + 情绪日记 NLP 分析 + 风险预警，214 个测试全部通过）  
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
| 阶段二：核心健康监测 | ⬜ 未开始 | 0% |
| 阶段三：智能问诊助手 | 🔄 进行中 | 80%（4/5 任务完成，T013 待实现）|
| 阶段四：生活方式干预 | 🔄 进行中 | 33%（1/3 任务完成，T014/T015 待实现）|
| 阶段五：智能家居联动 | ⬜ 未开始 | 0% |
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

### T005 - 慢病趋势预测
- [ ] 收集并清洗时序健康数据集（血压/血糖）
- [ ] 训练 LSTM 或 TimesNet 时序预测模型
- [ ] 设置异常阈值规则引擎（可配置每位成员的个性化阈值）
- [ ] 实现预警通知（App 推送 / 微信通知）
- [ ] 编写预测模型评估报告

### T006 - 睡眠质量分析
- [ ] 对接可穿戴设备睡眠数据接口
- [ ] 实现睡眠分期分析（深睡/浅睡/REM）
- [ ] 计算睡眠评分并生成改善建议
- [ ] 检测潜在呼吸暂停风险信号（SpO₂ 波动）

### T007 - 儿童生长发育评估
- [ ] 集成 WHO 儿童生长标准数据
- [ ] 实现身高/体重/BMI 百分位计算与可视化
- [ ] 追踪发育里程碑（运动/语言/认知）
- [ ] 生成儿科就诊前评估摘要

### T008 - 老人跌倒风险评估
- [ ] 定义跌倒风险评估指标（活动频率、步态数据、疾病史）
- [ ] 开发风险评分模型
- [ ] 实现长时间不活动异常检测（接入智能家居传感器）
- [ ] 紧急联系人告警推送

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

### T013 - 皮肤/伤口照片辅助分析
- [ ] 接入多模态模型（GPT-4o Vision / LLaVA）
- [ ] 开发图片上传与预处理流程
- [ ] 输出初步判断（正常/关注/建议就医）+ 免责声明
- [ ] 日志记录所有分析请求（用于审计）

---

## 阶段四：生活方式干预

### T014 - 个性化营养规划
- [ ] 建立食物营养数据库（接入 USDA FoodData / 中国食物成分表）
- [ ] 基于健康档案和实验室指标生成营养目标
- [ ] LLM 生成个性化每周食谱
- [ ] 支持饮食偏好和过敏原设置
- [ ] 对接超市 API 或生成购物清单

### T015 - 运动方案生成与追踪
- [ ] 用户体能评估问卷设计
- [ ] LLM 生成个性化运动计划（类型/强度/频率）
- [ ] 接入运动数据追踪（步数/心率/卡路里）
- [ ] 动态调整计划（基于执行情况和身体反馈）

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

### T017 - 环境健康监控
- [ ] 集成传感器数据接入（PM2.5、CO₂、温湿度）
- [ ] 建立环境健康阈值规则
- [ ] 联动智能家居设备（米家/Home Assistant API）
- [ ] 环境报告可视化 Dashboard

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
| P2 🟢 | T006 睡眠分析 | 中 | 中 | ⬜ 未开始 |
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
