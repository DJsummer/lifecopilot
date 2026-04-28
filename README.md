# LifePilot — 家庭健康管理 AI 系统

> 用 AI 技术帮助家庭轻松管理健康，让每个成员都有自己的智能健康助理。

[English](README_EN.md)

[![Python](https://img.shields.io/badge/Python-3.9-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-1.0.0-green)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-510%2F510-brightgreen)](#测试)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 功能概览

| 功能 | 状态 | 说明 |
|------|------|------|
| 🔐 家庭账户注册 / 登录 | ✅ 已完成 | JWT 认证，access + refresh token，家庭成员 RBAC |
| 📊 健康数据录入 | ✅ 已完成 | 血压/血糖/体重/心率等 10 种指标，CSV 批量导入 |
| 💬 健康 RAG 问答助手 | ✅ 已完成 v3 | OpenAI Tool Calling 三工具 + 多成员记忆隔离 |
| 📚 健康知识库 | ✅ 已完成 | disease / red_flag / triage 三分区，支持批量导入 |
| 🔬 检验单 AI 解读 | ✅ 已完成 v1 | OCR + LLM 结构化解读 + 异常趋势对比 |
| 💊 用药管理提醒 | ✅ 已完成 v1 | LLM 药物说明 + 依从性记录 + 相互作用检查 |
| 📈 健康周报/月报 | ✅ 已完成 v1 | LLM 总结 + 指标统计 + 依从性汇总 + 异常事件提取 |
| 🗒️ 就医准备助手 | ✅ 已完成 | LLM 生成中/英文就诊摘要 + 自动聊天快照 |
| 📝 症状日记 NLP 分析 | ✅ 已完成 | LLM 结构化提取症状 + 严重度评分 + 就医建议 |
| 🧠 心理健康筛查 | ✅ 已完成 | PHQ-9/GAD-7 评分 + 情绪日记 NLP + 风险预警 + 干预资源 |
| 🩺 皮肤/伤口辅助分析 | ✅ 已完成 | GPT-4o / Ollama / 本地 Qwen2-VL 三后端，支持多供应商 API Key |
| 🥗 个性化营养规划 | ✅ 已完成 | BMR 公式 + LLM 营养目标 + 每周食谱 + 饮食日志估算 |
| 🏃 运动方案生成与追踪 | ✅ 已完成 | 体能评估问卷 + LLM 7天计划 + METs 热量估算 + 每周汇总 |
| 🔔 慢病趋势预测与告警 | ✅ 已完成 | 个性化阈值规则引擎 + 自动告警 + 最小二乘趋势分析 + LLM 解读 |
| 😴 睡眠质量分析 | ✅ 已完成 | 多维评分算法 + 呼吸暂停风险检测 + 趋势汇总 + LLM 改善建议 |
| 👶 児童生长发育评估 | ✅ 已完成 | WHO LMS 百分位 + Z-score + 5类里程碑追踪 + LLM 报告 |
| 👴 老人跌倒风险评估 | ✅ 已完成 | 改进版 Morse/Hendrich II 评分 + 不活动检测 + 紧急联系人告警 + LLM 干预建议 |
| 🌡️ 环境健康监控 | ✅ 已完成 | PM2.5/CO₂/温湿度/VOC/噪音 + WHO阈值耦警 + 小米/Home Assistant接入 + LLM建议 |
| 🔒 API 限流与安全防护 | ✅ 已完成 | OWASP安全头 + slowapi限流 + X-Request-ID请求跟踪 + 输入校验 |

---

## RAG 问答助手架构（v3）

参考 [FamilyHealthyAgent](https://github.com/qianandgrace/FamilyHealthyAgent) 设计，实现真正的 **OpenAI Tool Calling** 两轮推理：

```
用户提问
   │
   ▼
Round 1 — LLM 自主决定调用哪些工具（tool_choice=auto）
   │
   ├─► check_red_flag   → 搜索危险症状库（20条紧急症状）
   │                       分数>阈值 → 提示立即就医/拨打120
   ├─► get_triage       → 搜索分诊导诊库（11个科室指南）
   │                       "挂什么科/看哪个科" 等问题
   └─► search_disease   → 搜索疾病科普/药物知识库
                          默认兜底，支持 category 过滤
   │
   ▼
Execute — asyncio.gather 并行执行工具（Qdrant 向量检索）
   │
   ▼
Round 2 — LLM 读取工具结果，生成最终回答（支持流式 SSE）
```

**核心特性：**
- **多成员记忆隔离**：每位成员（`member_id`）独立会话历史，互不干扰
- **个体化约束**：将成员档案（年龄/慢病/用药/近期指标）注入 system prompt
- **可追溯引用**：回答附带 `sources`（来源/标题/分类）
- **CrossEncoder Rerank**：可选，`USE_RERANKER=true` 时对检索结果重排（`ms-marco-MiniLM-L-6-v2`）
- **Redis 查询缓存**：热门问题 5 分钟缓存，极速响应

---

## 技术架构

```
FastAPI ──► PostgreSQL  （用户/成员/用药/报告，SQLAlchemy async）
        ──► InfluxDB    （血压/心率等时序数据）
        ──► Qdrant      （RAG 向量检索，disease/red_flag/triage 三分区）
        ──► Redis       （查询缓存 5min + Celery 任务队列）
        ──► Celery      （OCR/LLM 异步任务）

知识库层：
  表格感知分块（Markdown 表格整体保留）
  → EmbeddingService（OpenAI text-embedding-3-small，可替换本地 bge-m3）
  → Qdrant upsert（MD5 hash 幂等，category 字段分区）
  → CrossEncoder Rerank（可选）
  → Redis 查询缓存

问答层：
  OpenAI Tool Calling Round 1（工具选择）
  → asyncio.gather 并行执行三工具
  → OpenAI Round 2（流式生成最终回答）
```

详见 [doc/architecture.md](doc/architecture.md)

---

## 快速开始

### 前置条件

- Docker 24+ & Docker Compose 2.20+
- Git

### 1. 克隆仓库

```bash
git clone git@github.com:DJsummer/lifecopilot.git
cd lifecopilot
```

### 2. 配置环境变量

```bash
cp .env.example .env.dev
# 必填项：
# SECRET_KEY        JWT 签名密钥（随机字符串）
# POSTGRES_PASSWORD 数据库密码
# REDIS_PASSWORD    Redis 密码
# OPENAI_API_KEY    LLM/Embedding API 密钥
# OPENAI_BASE_URL   可替换为阿里百炼/本地 Ollama 等兼容接口
```

### 3. 启动开发环境

```bash
make dev
```

服务启动后访问：
- **API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health
- **Qdrant 控制台**：http://localhost:6333/dashboard

### 4. 初始化数据库

```bash
make db-migrate
```

### 5. 导入健康知识库（三库一键导入）

```bash
# 导入示例数据（disease 科普 + red_flag 危险症状 + triage 分诊导诊）
make import-all-knowledge

# 或分开导入
make import-red-flag    # 危险症状库（20条紧急症状）
make import-triage      # 分诊导诊库（11个科室指南）
make import-sample      # 疾病科普库（示例文章）

# 导入丁香医生文章（填写 data/dxy_urls.txt 后）
make dxy-import URL_FILE=data/dxy_urls.txt

# 导入本地文档目录
make import-dir DIR=docs/medical/ SOURCE="丁香医生" CATEGORY=内科
```

---

## API 说明

### 健康问答

```
POST   /api/v1/chat/          同步问答（两轮 Tool Calling）
POST   /api/v1/chat/stream    流式问答（SSE，Round 2 逐 token 返回）
DELETE /api/v1/chat/sessions/{id}   清除指定会话
DELETE /api/v1/chat/sessions/me     清除当前成员会话历史
```

### 知识库管理

```
POST   /api/v1/chat/knowledge           摄入文档（admin only）
DELETE /api/v1/chat/knowledge/{source}  按来源删除（admin only）
GET    /api/v1/chat/knowledge/stats     知识库统计（admin only）
```

### 健康数据

```
POST   /api/v1/health/{member_id}/records         录入健康指标
POST   /api/v1/health/{member_id}/records/batch   批量录入（≤500条）
POST   /api/v1/health/{member_id}/records/import-csv  CSV 导入
GET    /api/v1/health/{member_id}/records         查询记录（支持过滤/分页）
GET    /api/v1/health/{member_id}/summary         各指标统计摘要
DELETE /api/v1/health/{member_id}/records/{id}    删除单条记录
```

### 认证

```
POST   /api/v1/auth/register              注册家庭账户
POST   /api/v1/auth/login                 登录
POST   /api/v1/auth/refresh               刷新 token
GET    /api/v1/auth/me                    当前成员信息
GET    /api/v1/auth/family                家庭信息+成员列表（admin）
POST   /api/v1/auth/family/members        添加成员（admin）
PATCH  /api/v1/auth/family/members/{id}   更新成员信息
DELETE /api/v1/auth/family/members/{id}   删除成员（admin）
```

### 检验单 AI 解读

```
POST   /api/v1/lab-reports/{member_id}/upload         上传检验单（JPG/PNG/PDF/TXT）+ AI 解读
GET    /api/v1/lab-reports/{member_id}                报告列表（按类型过滤）
GET    /api/v1/lab-reports/{member_id}/{report_id}    报告详情
DELETE /api/v1/lab-reports/{member_id}/{report_id}    删除报告
GET    /api/v1/lab-reports/{member_id}/compare        异常项趋势对比
```

### 用药管理

```
POST   /api/v1/medications/{member_id}                          新增用药方案（含 LLM 自动说明）
GET    /api/v1/medications/{member_id}                          用药方案列表（按 status 过滤）
GET    /api/v1/medications/{member_id}/{med_id}                 用药方案详情
PATCH  /api/v1/medications/{member_id}/{med_id}                 更新用药方案
DELETE /api/v1/medications/{member_id}/{med_id}                 删除用药方案
POST   /api/v1/medications/{member_id}/{med_id}/reminders       添加提醒时间
DELETE /api/v1/medications/{member_id}/{med_id}/reminders/{rid} 删除提醒时间
POST   /api/v1/medications/{member_id}/{med_id}/adherence       记录服药依从性
GET    /api/v1/medications/{member_id}/{med_id}/adherence       依从性记录列表
GET    /api/v1/medications/{member_id}/{med_id}/adherence/stats 依从性统计（按时率）
POST   /api/v1/medications/{member_id}/interaction-check        多药物相互作用风险检查

# 延迟至 T019
POST   /api/v1/reports/{member_id}/generate                    生成周报或月报（LLM 总结 + 指标统计）
GET    /api/v1/reports/{member_id}                             报告历史列表（可按 weekly/monthly 过滤）
GET    /api/v1/reports/{member_id}/{report_id}                 报告详情（含 metric_stats / notable_events）
DELETE /api/v1/reports/{member_id}/{report_id}                 删除报告

# 就医准备助手（T019）
POST   /api/v1/visit/{member_id}                              生成就诊摘要（中/英文/双语）
GET    /api/v1/visit/{member_id}                              摘要历史列表
GET    /api/v1/visit/{member_id}/{visit_id}                   摘要详情（全快照 + LLM 文本）
DELETE /api/v1/visit/{member_id}/{visit_id}                   删除摘要

# 症状日记 NLP 分析（T011）
POST   /api/v1/symptoms/{member_id}               记录症状日记并 LLM 分析
GET    /api/v1/symptoms/{member_id}               症状日记列表（可按 advice_level 过滤）
GET    /api/v1/symptoms/{member_id}/{log_id}       症状日记详情
DELETE /api/v1/symptoms/{member_id}/{log_id}       删除症状日记

# 心理健康筛查（T016）
GET    /api/v1/mental-health/phq9/questions        获取 PHQ-9 抑郁自评量表 9 题
GET    /api/v1/mental-health/gad7/questions        获取 GAD-7 广泛性焦虑量表 7 题
POST   /api/v1/mental-health/{member_id}/diary     记录情绪日记（LLM NLP 分析）
POST   /api/v1/mental-health/{member_id}/assess    提交 PHQ-9/GAD-7 答案并评分
GET    /api/v1/mental-health/{member_id}           心理健康记录列表（可按 risk_level 过滤）
GET    /api/v1/mental-health/{member_id}/{log_id}  记录详情
DELETE /api/v1/mental-health/{member_id}/{log_id}  删除记录

# 皮肤/伤口辅助分析（T013）
POST   /api/v1/skin/{member_id}/analyze            上传照片 + AI 辅助分析
GET    /api/v1/skin/{member_id}/analyses           分析历史列表（可按 result 过滤）
GET    /api/v1/skin/{member_id}/analyses/{id}      分析详情
DELETE /api/v1/skin/{member_id}/analyses/{id}      删除分析记录

# 个性化营养规划（T014）
GET    /api/v1/nutrition/foods                              食物搜索
POST   /api/v1/nutrition/{member_id}/goal                   创建/更新营养目标（LLM 生成）
GET    /api/v1/nutrition/{member_id}/goal                   获取营养目标
POST   /api/v1/nutrition/{member_id}/meal-plans             生成本周食谱
GET    /api/v1/nutrition/{member_id}/meal-plans             食谱列表
GET    /api/v1/nutrition/{member_id}/meal-plans/{id}        食谱详情
DELETE /api/v1/nutrition/{member_id}/meal-plans/{id}        删除食谱
POST   /api/v1/nutrition/{member_id}/diet-logs              记录饮食（LLM 估算营养素）
GET    /api/v1/nutrition/{member_id}/diet-logs              饮食日志列表
GET    /api/v1/nutrition/{member_id}/diet-logs/summary      日摄入营养汇总
DELETE /api/v1/nutrition/{member_id}/diet-logs/{id}         删除日志

# 运动方案生成与追踪（T015）
POST   /api/v1/fitness/{member_id}/assessment         创建/更新体能评估问卷
GET    /api/v1/fitness/{member_id}/assessment         获取体能评估
POST   /api/v1/fitness/{member_id}/plans              LLM 生成本周运动计划（7天JSON）
GET    /api/v1/fitness/{member_id}/plans              计划历史列表
GET    /api/v1/fitness/{member_id}/plans/active       当前活跃计划
POST   /api/v1/fitness/{member_id}/logs               记录运动日志（METs 热量 + LLM 反馈）
GET    /api/v1/fitness/{member_id}/logs               日志列表（支持日期过滤）
GET    /api/v1/fitness/{member_id}/logs/{id}          日志详情
DELETE /api/v1/fitness/{member_id}/logs/{id}          删除日志
GET    /api/v1/fitness/{member_id}/summary/weekly     每周运动汇总统计

# 慢病趋势预测与告警（T005）
GET    /api/v1/alerts/{member_id}/thresholds/defaults 查看系统内置默认阈值
POST   /api/v1/alerts/{member_id}/thresholds          设置/更新个性化阈值（upsert）
GET    /api/v1/alerts/{member_id}/thresholds          阈值列表
DELETE /api/v1/alerts/{member_id}/thresholds/{metric} 删除阈值（恢复默认）
GET    /api/v1/alerts/{member_id}/alerts              告警列表（多维过滤）
GET    /api/v1/alerts/{member_id}/alerts/{id}         告警详情
PATCH  /api/v1/alerts/{member_id}/alerts/{id}/acknowledge 确认告警
DELETE /api/v1/alerts/{member_id}/alerts/{id}         删除告警
POST   /api/v1/alerts/{member_id}/trends              生成趋势快照（LLM 解读可选）
GET    /api/v1/alerts/{member_id}/trends              趋势快照列表
GET    /api/v1/alerts/{member_id}/trends/latest       获取某指标最新趋势快照

# 睡眠质量分析（T006）
POST   /api/v1/sleep/{member_id}/records              录入睡眠数据（自动评分 + LLM 建议）
GET    /api/v1/sleep/{member_id}/records              睡眠记录列表（可按质量过滤）
GET    /api/v1/sleep/{member_id}/records/{id}         记录详情
DELETE /api/v1/sleep/{member_id}/records/{id}         删除记录
GET    /api/v1/sleep/{member_id}/summary              近 N 天趋势汇总统计

# 児童生长发育评估（T007）
POST   /api/v1/growth/{member_id}/records              录入身高/体重/头围（WHO 百分位自动计算）
GET    /api/v1/growth/{member_id}/records              生长记录列表
GET    /api/v1/growth/{member_id}/records/{id}         记录详情
DELETE /api/v1/growth/{member_id}/records/{id}         删除记录
POST   /api/v1/growth/{member_id}/milestones/init      初始化系统预设里程碑（24 条）
POST   /api/v1/growth/{member_id}/milestones           添加自定义里程碑
GET    /api/v1/growth/{member_id}/milestones           里程碑列表（可按类型/状态过滤）
PATCH  /api/v1/growth/{member_id}/milestones/{id}/achieve  标记里程碑已达成
DELETE /api/v1/growth/{member_id}/milestones/{id}      删除自定义里程碑
GET    /api/v1/growth/{member_id}/summary              生长发育概览（最新记录+里程碑统计）

# 老人跌倒风险评估（T008）
POST   /api/v1/fall-risk/{member_id}/assessments           提交问卷（11项 Morse+Hendrich 评分 + LLM 建议）
GET    /api/v1/fall-risk/{member_id}/assessments           评估列表（可按 risk_level 过滤）
GET    /api/v1/fall-risk/{member_id}/assessments/latest    最新评估
GET    /api/v1/fall-risk/{member_id}/assessments/{id}      评估详情
DELETE /api/v1/fall-risk/{member_id}/assessments/{id}      删除评估
POST   /api/v1/fall-risk/{member_id}/inactivity/check      触发不活动检测（返回 InactivityLog 或 null）
GET    /api/v1/fall-risk/{member_id}/inactivity            不活动记录列表
GET    /api/v1/fall-risk/{member_id}/summary               综合概览（评估统计 + 最新风险等级）

# 环境健康监控（T017）
POST   /api/v1/environment/{member_id}/records                 手动录入环境指标（阈值自动耦警标注）
POST   /api/v1/environment/{member_id}/records/batch           批量录入（最多 200 条）
GET    /api/v1/environment/{member_id}/records                 记录列表（支持指标类型/位置/时间窗口/告警过滤）
GET    /api/v1/environment/{member_id}/records/{id}            记录详情
DELETE /api/v1/environment/{member_id}/records/{id}            删除记录
GET    /api/v1/environment/{member_id}/summary                室内环境综合摘要（各指标最新局 + 空气质量等级）
POST   /api/v1/environment/{member_id}/advice                  生成 LLM 环境建议
GET    /api/v1/environment/{member_id}/advice                  历史建议列表
POST   /api/v1/environment/{member_id}/webhook/xiaomi          小米传感器 Webhook 接入
POST   /api/v1/environment/{member_id}/webhook/home-assistant  Home Assistant Webhook 接入
```

---

## 常用命令

```bash
# 开发
make dev              # 启动开发环境（热更新）
make dev-d            # 后台启动
make down             # 停止所有服务
make logs-api         # 查看 API 日志
make shell            # 进入 API 容器

# 数据库
make db-migrate       # 执行数据库迁移
make db-shell         # 进入 PostgreSQL 终端

# 知识库
make import-all-knowledge   # 一键导入三库（disease/red_flag/triage）
make import-red-flag        # 仅导入危险症状库
make import-triage          # 仅导入分诊导诊库
make import-sample          # 仅导入疾病科普示例

# 测试
make test-local       # 本地运行测试（推荐开发时使用）
make test             # Docker 内运行测试
make test-cov         # 生成覆盖率报告

# 代码质量
make lint             # ruff 代码检查
make format           # ruff 格式化
```

---

## 测试

项目使用 **pytest + pytest-asyncio** 进行后端测试，SQLite in-memory 隔离，无需启动外部服务。

```bash
pip install -r requirements-test.txt
python -m pytest tests/ --ignore=tests/e2e -v
```

**测试状态：510/510 通过 ✅**

| 测试文件 | 内容 | 数量 |
|----------|------|------|
| `test_security.py` | JWT/密码哈希单元测试 | 11 |
| `test_auth.py` | 注册/登录/refresh/me 集成测试 | 14 |
| `test_members.py` | 家庭成员 CRUD | 15 |
| `test_health.py` | 健康数据录入/查询/CSV 导入 | 17 |
| `test_chat.py` | RAG 问答/工具/知识库 API | 21 |
| `test_lab_report.py` | 检验单上传/AI 解读/趋势 | 20 |
| `test_medication.py` | 用药管理/依从性/相互作用 | 23 |
| `test_report.py` | 周报/月报生成/列表/详情/删除 | 21 |
| `test_visit.py` | 就医准备摘要生成/列表/详情/删除 | 21 |
| `test_symptom.py` | 症状日记 NLP 分析/列表/详情/删除 | 20 |
| `test_mental_health.py` | PHQ-9/GAD-7 量表评分 + 情绪日记 NLP | 27 |
| `test_skin_analysis.py` | 皮肤/伤口照片分析（三后端 + 多供应商） | 23 |
| `test_nutrition.py` | 营养目标/食谱/饮食日志/服务单元 | 32 |
| `test_alerts.py` | 慢病阈值/告警/趋势分析 | 43 |
| `test_sleep.py` | 睡眠记录/评分/趋势汇总 | 25 |
| `test_growth.py` | 儿童生长/WHO百分位/里程碑 | 32 |
| `test_fall_risk.py` | 跌倒风险评估/不活动检测/评分算法 | 28 |
| `test_environment.py` | 环境指标录入/阈值告警/Webhook/LLM建议 | 52 |
| `test_exercise.py` | 运动方案/追踪/汇总 | 38 |
| `test_system.py` | 健康检查 | 2 |

---

## 知识库数据

| 文件 | 分类（`category`） | 对应工具 | 条目数 |
|------|--------------------|----------|--------|
| `data/red_flag_symptoms.json` | `red_flag` | `check_red_flag` | 20条（胸痛/脑卒中/心脏骤停等） |
| `data/triage_guide.json` | `triage` | `get_triage` | 11条（各症状挂号指南） |
| `data/sample_articles.json` | `disease` | `search_disease` | 5条（高血压/糖尿病等示例） |
| `data/dxy_urls.txt` | — | 爬虫 URL 列表 | 填写后运行 `make dxy-import` |

扩充知识库：在对应 JSON 文件追加条目后，重新运行导入命令（`upsert` 幂等，不会产生重复）。

---

## 项目结构

```
lifecopilot/
├── src/
│   ├── main.py                    # FastAPI 应用入口（v0.4.0）
│   ├── core/                      # 配置 / 数据库 / Qdrant / 日志
│   ├── models/                    # SQLAlchemy ORM 模型（8个模型文件）
│   ├── api/v1/routers/            # 12 组路由
│   ├── services/
│   │   ├── knowledge_service.py   # 向量化 + 检索 + Rerank + Redis 缓存
│   │   ├── chat_service.py        # Tool Calling 两轮推理 + 多成员会话
│   │   ├── embedding_service.py   # Embedding 抽象层（OpenAI / bge-m3）
│   │   ├── skin_analysis_service.py  # 皮肤分析（GPT-4o / Ollama / 本地 Qwen2-VL）
│   │   └── nutrition_service.py   # 营养目标 + 食谱 + 饮食日志 LLM 分析
│   └── workers/                   # Celery 异步任务
├── data/
│   ├── red_flag_symptoms.json     # 危险症状库（20条）
│   ├── triage_guide.json          # 分诊导诊库（11条）
│   ├── sample_articles.json       # 疾病科普示例（5条）
│   └── dxy_urls.txt               # 丁香医生文章 URL 列表
├── scripts/
│   ├── import_knowledge.py        # 批量导入工具（JSON/目录/单文件/PDF）
│   └── dxy_crawler.py             # 丁香医生文章爬虫（礼貌间隔，个人学习用）
├── alembic/                       # 数据库迁移脚本
├── tests/                         # pytest 测试套件（82个用例）
├── docker/                        # 各服务 Docker 配置
├── doc/architecture.md            # 系统架构设计文档
├── Makefile                       # 快捷命令
└── TASKS.md                       # 项目任务清单与进度
```

---

## 开发进度

详见 [TASKS.md](TASKS.md)

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| 阶段零：Docker 部署基础设施 | ✅ 已完成 | 100% |
| 阶段一：基础架构搭建 | ✅ 已完成 | 100% |
| 阶段二：核心健康监测 | 🔄 进行中 | 15%（健康数据录入已完成）|
| 阶段三：智能问诊助手（RAG） | ✅ 已完成 | 100%（知识库+RAG问答+检验单+症状日记+皮肤分析）|
| 阶段四：生活方式干预 | 🔄 进行中 | 67%（营养规划已完成，T015 待实现）|
| 阶段五～七：前端/报告/部署 | 🔄 进行中 | 50%（T018~T020 已完成）|

**下一步（优先级 P1）**：T018 健康周报

---

## 免责声明

本系统提供的所有 AI 分析结果（症状判断、检验单解读、用药建议等）**仅供参考，不构成医疗诊断意见**。如有健康问题请及时就医，遵从执业医师的诊断和建议。紧急情况请立即拨打 **120**。
