# LifePilot — Family Health AI System

> AI-powered health management for the whole family — every member gets their own intelligent health assistant.

[![Python](https://img.shields.io/badge/Python-3.9-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-1.0.0-green)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-350%2F350-brightgreen)](#testing)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[中文文档](README.md)

---

## Features

| Feature | Status | Description |
|---------|--------|-------------|
| 🔐 Family Account & Auth | ✅ Done | JWT authentication, access + refresh tokens, family RBAC |
| 📊 Health Data Entry | ✅ Done | 10 metrics (BP / glucose / weight / heart rate …), CSV bulk import |
| 💬 Health RAG Chatbot | ✅ Done v3 | OpenAI Tool Calling (3 tools) + per-member memory isolation |
| 📚 Health Knowledge Base | ✅ Done | 3-partition Qdrant store: `disease` / `red_flag` / `triage` |
| 🔬 Lab Report AI Interpretation | ✅ Done v1 | OCR + LLM structured analysis + abnormal trend comparison |
| 📊 Medication Management | ✅ Done v1 | LLM drug explanation + adherence tracking + interaction check |
| 📈 Weekly / Monthly Reports | ✅ Done v1 | LLM summary + metric stats + adherence overview + notable events |
| 🏥 Pre-Visit Assistant | ✅ Done v1 | Structured visit summary (ZH/EN) + auto-aggregated medication / metrics / lab snapshots |
| 📝 Symptom Diary NLP | ✅ Done v1 | LLM symptom extraction + severity score (1-10) + visit advice level |
| 🧠 Mental Health Screening | ✅ Done v1 | PHQ-9/GAD-7 scoring + emotion diary NLP + risk alert + intervention resources |
| 🩺 Skin / Wound Photo Analysis | ✅ Done | GPT-4o / Ollama / local Qwen2-VL · multi-provider API key support |
| 🥗 Personalised Nutrition Plan | ✅ Done | BMR formula + LLM nutrition goals + weekly meal plan + diet log analysis |
| 🏃 Exercise Plan & Tracking | ✅ Done | Fitness assessment + LLM 7-day plan + METs calorie estimation + weekly summary |
| 🔔 Chronic Disease Alerts | ✅ Done | Per-member threshold engine + auto-alerts on entry + linear trend analysis + LLM insight |

---

## RAG Chatbot Architecture (v3)

Inspired by [FamilyHealthyAgent](https://github.com/qianandgrace/FamilyHealthyAgent), implementing genuine **OpenAI Tool Calling** two-round inference:

```
User question
   │
   ▼
Round 1 — LLM decides which tools to call (tool_choice=auto)
   │
   ├─► check_red_flag   → Search danger-symptom library (20 emergency entries)
   │                       Score > threshold → prompt user to call 120 / go to ER
   ├─► get_triage       → Search triage / department-routing library (11 guides)
   │                       Triggered by "which department / what specialist" questions
   └─► search_disease   → Search disease & medication knowledge base (default)
   │
   ▼
Execute — asyncio.gather parallel tool execution (Qdrant vector search)
   │
   ▼
Round 2 — LLM reads tool results, generates final answer (streaming SSE supported)
```

**Key capabilities:**
- **Per-member memory isolation**: each `member_id` has its own conversation history
- **Personalised context injection**: member profile (age / chronic conditions / medications / recent metrics) injected into system prompt
- **Traceable citations**: responses include `sources` (origin / title / category)
- **CrossEncoder Rerank**: optional, set `USE_RERANKER=true` (`ms-marco-MiniLM-L-6-v2`)
- **Redis query cache**: 5-minute cache for hot queries

---

## Technical Architecture

```
FastAPI ──► PostgreSQL   (users / members / medications / reports — SQLAlchemy async)
        ──► InfluxDB     (time-series health metrics: BP, heart rate, etc.)
        ──► Qdrant       (RAG vector search — disease / red_flag / triage partitions)
        ──► Redis        (query cache 5 min + Celery broker)
        ──► Celery       (async OCR / LLM tasks)

Knowledge layer:
  Table-aware chunking (Markdown tables kept intact)
  → EmbeddingService (OpenAI text-embedding-3-small; swappable to local bge-m3)
  → Qdrant upsert (MD5-hash idempotency, category-based partitioning)
  → CrossEncoder Rerank (optional)
  → Redis query cache

Chat layer:
  OpenAI Tool Calling Round 1 (tool selection)
  → asyncio.gather parallel tool execution
  → OpenAI Round 2 (streaming final answer via SSE)
```

See [doc/architecture.md](doc/architecture.md) for full design documentation.

---

## Quick Start

### Prerequisites

- Docker 24+ & Docker Compose 2.20+
- Git

### 1. Clone the repository

```bash
git clone git@github.com:DJsummer/lifecopilot.git
cd lifecopilot
```

### 2. Configure environment variables

```bash
cp .env.example .env.dev
# Required fields:
# SECRET_KEY          JWT signing secret (random string)
# POSTGRES_PASSWORD   Database password
# REDIS_PASSWORD      Redis password
# OPENAI_API_KEY      LLM / Embedding API key
# OPENAI_BASE_URL     Can be replaced with Alibaba Bailian / local Ollama compatible endpoint
```

### 3. Start the development environment

```bash
make dev
```

Once started:
- **API docs**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health
- **Qdrant dashboard**: http://localhost:6333/dashboard

### 4. Run database migrations

```bash
make db-migrate
```

### 5. Import the health knowledge base

```bash
# Import all three libraries at once
make import-all-knowledge

# Or import individually
make import-red-flag    # Danger symptoms (20 emergency entries)
make import-triage      # Triage / department routing (11 guides)
make import-sample      # Disease knowledge sample articles

# Import from DXY (fill in data/dxy_urls.txt first)
make dxy-import URL_FILE=data/dxy_urls.txt

# Import a local document directory
make import-dir DIR=docs/medical/ SOURCE="DXY" CATEGORY=internal-medicine
```

---

## API Reference

### Health Chatbot

```
POST   /api/v1/chat/              Synchronous Q&A (two-round Tool Calling)
POST   /api/v1/chat/stream        Streaming Q&A (SSE, Round 2 token-by-token)
DELETE /api/v1/chat/sessions/{id} Clear a specific session
DELETE /api/v1/chat/sessions/me   Clear current member's session history
```

### Knowledge Base Management

```
POST   /api/v1/chat/knowledge              Ingest document (admin only)
DELETE /api/v1/chat/knowledge/{source}     Delete by source (admin only)
GET    /api/v1/chat/knowledge/stats        Knowledge base statistics (admin only)
```

### Lab Report AI Interpretation

```
POST   /api/v1/lab-reports/{member_id}/upload          Upload report (JPG/PNG/PDF/TXT) + AI analysis
GET    /api/v1/lab-reports/{member_id}                 List reports (filterable by type)
GET    /api/v1/lab-reports/{member_id}/{report_id}     Report detail (with structured items)
DELETE /api/v1/lab-reports/{member_id}/{report_id}     Delete report
GET    /api/v1/lab-reports/{member_id}/compare         Abnormal-item trend comparison
```

### Health Data

```
POST   /api/v1/health/{member_id}/records              Record a health metric
POST   /api/v1/health/{member_id}/records/batch        Bulk entry (≤ 500 records)
POST   /api/v1/health/{member_id}/records/import-csv   CSV import
GET    /api/v1/health/{member_id}/records              Query records (filter + paginate)
GET    /api/v1/health/{member_id}/summary              Per-metric statistics summary
DELETE /api/v1/health/{member_id}/records/{id}         Delete a record
```

### Authentication

```
POST   /api/v1/auth/register                Register a family account
POST   /api/v1/auth/login                   Login
POST   /api/v1/auth/refresh                 Refresh access token
GET    /api/v1/auth/me                      Current member info
GET    /api/v1/auth/family                  Family info + member list (admin)
POST   /api/v1/auth/family/members          Add a member (admin)
PATCH  /api/v1/auth/family/members/{id}     Update member info
DELETE /api/v1/auth/family/members/{id}     Remove member (admin)
```

---

## Common Commands

```bash
# Development
make dev              # Start dev environment (hot-reload)
make dev-d            # Start in background
make down             # Stop all services
make logs-api         # Tail API logs
make shell            # Shell into API container

# Database
make db-migrate       # Apply database migrations
make db-shell         # Open PostgreSQL interactive terminal

# Knowledge base
make import-all-knowledge   # Import all three libraries
make import-red-flag        # Import danger-symptom library only
make import-triage          # Import triage library only
make import-sample          # Import disease knowledge samples only

# Testing
make test-local       # Run tests locally (recommended during development)
make test             # Run tests inside Docker
make test-cov         # Generate coverage report

# Code quality
make lint             # ruff lint
make format           # ruff format
```

---

## Testing

The project uses **pytest + pytest-asyncio** with an SQLite in-memory database — no external services needed.

```bash
pip install -r requirements-test.txt
python -m pytest tests/ --ignore=tests/e2e -v
```

**Test status: 214 / 214 passing ✅**

| Test file | Coverage | Count |
|-----------|----------|-------|
| `test_security.py` | JWT / password hashing unit tests | 11 |
| `test_auth.py` | Register / login / refresh / me integration | 14 |
| `test_members.py` | Family member CRUD | 15 |
| `test_health.py` | Health data entry / query / CSV import | 17 |
| `test_chat.py` | RAG chatbot / tool calling / knowledge API | 21 |
| `test_lab_report.py` | Lab report upload / AI interpretation / trend | 20 |
| `test_medication.py` | Medication management / adherence / interactions | 23 |
| `test_report.py` | Weekly/monthly report generate / list / detail / delete | 21 |
| `test_visit.py` | Pre-visit summary generate / list / detail / delete | 21 |
| `test_symptom.py` | Symptom diary NLP / list / detail / delete | 20 |
| `test_mental_health.py` | PHQ-9/GAD-7 scoring + emotion diary NLP | 27 |
| `test_system.py` | Health check | 2 |

---

## Knowledge Base Data

| File | Category | Tool | Entries |
|------|----------|------|---------|
| `data/red_flag_symptoms.json` | `red_flag` | `check_red_flag` | 20 (chest pain / stroke / cardiac arrest …) |
| `data/triage_guide.json` | `triage` | `get_triage` | 11 (department-routing guides) |
| `data/sample_articles.json` | `disease` | `search_disease` | 5 (hypertension / diabetes samples) |
| `data/dxy_urls.txt` | — | crawler URL list | Fill in then run `make dxy-import` |

To expand the knowledge base, append entries to the corresponding JSON file and re-run the import command. `upsert` is idempotent — no duplicates will be created.

---

## Project Structure

```
lifecopilot/
├── src/
│   ├── main.py                    # FastAPI entry point (v0.5.0)
│   ├── core/                      # Config / database / Qdrant / logging
│   ├── models/                    # SQLAlchemy ORM models (5 model files)
│   ├── api/v1/routers/            # auth / health / chat / lab-reports routers
│   ├── services/
│   │   ├── knowledge_service.py   # Vectorisation + retrieval + rerank + Redis cache
│   │   ├── chat_service.py        # Tool Calling two-round inference + multi-member sessions
│   │   ├── lab_report_service.py  # OCR + LLM structured lab report interpretation
│   │   └── embedding_service.py   # Embedding abstraction (OpenAI / bge-m3)
│   └── workers/                   # Celery async tasks
├── data/
│   ├── red_flag_symptoms.json     # Danger symptom library (20 entries)
│   ├── triage_guide.json          # Triage / department routing library (11 entries)
│   ├── sample_articles.json       # Disease knowledge samples (5 entries)
│   └── dxy_urls.txt               # DXY article URL list
├── scripts/
│   ├── import_knowledge.py        # Bulk import tool (JSON / directory / single file / PDF)
│   └── dxy_crawler.py             # DXY article crawler (polite rate-limit, personal study use)
├── alembic/                       # Database migration scripts
├── tests/                         # pytest test suite (214 cases)
├── docker/                        # Per-service Docker configs
├── doc/architecture.md            # System architecture design document
├── Makefile                       # Shortcut commands
└── TASKS.md                       # Project task list and progress
```

---

## Progress

See [TASKS.md](TASKS.md) for full details.

| Phase | Status | Completion |
|-------|--------|------------|
| Phase 0: Docker infrastructure | ✅ Done | 100% |
| Phase 1: Core framework | ✅ Done | 100% |
| Phase 2: Health monitoring | 🔄 In progress | 15% (health data entry done) |
| Phase 3: AI health assistant (RAG) | 🔄 In progress | 70% (knowledge base + Tool Calling + lab report interpretation done) |
| Phase 4: Lifestyle intervention | ⬜ Not started | 0% |
| Phases 5–7: Frontend / reports / deployment | ⬜ Not started | 0% |

**Next up (P1)**: T018 Weekly Health Report

---

## Disclaimer

All AI analysis results produced by this system (symptom assessment, lab report interpretation, medication advice, etc.) are **for reference only and do not constitute medical diagnosis**. Please consult a licensed physician for any health concerns. **In an emergency, call your local emergency number immediately.**
