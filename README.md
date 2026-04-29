# Jenkins Log Intelligence Engine

A full-stack CI/CD intelligence platform built with FastAPI and vanilla JS. It intercepts Jenkins build failures, analyses logs with an LLM-backed root-cause engine, dispatches pipeline runs across a simulated worker pool, streams live commit activity to a real-time dashboard, and fires Slack/email alerts — all autonomously.

---

## Dashboard

Seven live pages served at `http://localhost:8000`:

| Page | Path | What it shows |
| --- | --- | --- |
| **Overview** | `/` | Live activity stream (commits → pipeline status), worker utilisation, queue depth, system health |
| **Queue Explorer** | `/queue` | All pipeline runs by status, wait times, database state |
| **Scheduler** | `/scheduler` | Kanban board (Queued → Scheduled → Running → Completed), decision log |
| **Workers** | `/workers` | Worker pool cards, assignment log, load timeline |
| **Webhooks** | `/webhooks` | Webhook event stream, simulated payload generator |
| **Backend Console** | `/backend` | API route health, live request feed, memory/CPU metrics |
| **Simulation** | `/simulation` | Chaos controls, job arrival randomiser, LLM analysis panel |

Every panel polls live data from the backend — no hardcoded placeholder values anywhere. Commits pushed via the GitHub webhook appear in the Live Activity Stream within 10 seconds.

---

## Architecture

```mermaid
flowchart TD
    A([Jenkins / GitHub\nWebhook]) -->|POST /webhook/jenkins\nPOST /webhook/github| B[Webhook Router\nHMAC verification]
    B -->|FINALIZED · FAILURE| C[Background Task\ntasks.py]

    C --> D[Log Fetcher\nJenkins REST API\n3× retry · 10 MB cap]
    D --> E[Log Parser\nANSI strip · error block\nextraction ±5 ctx lines]
    E --> F[Classifier\nregex rules YAML\nHIGH / MEDIUM / LOW]
    F --> G[Pattern Store\nhistorical matches\nPostgreSQL]
    F & G --> H{LLM Root Cause\nAnalyser}

    H -->|1st| I[Groq API]
    H -->|fallback| J[Anthropic Claude]
    H -->|offline| K[Template Engine]

    I & J & K --> L[Notifier\nSlack Block Kit\nHTML email]

    M([GitHub Push]) -->|webhook| N[Job Scheduler\nschedule_pipeline]
    N --> O[(PostgreSQL\nPipelineRun · Worker)]
    P[Celery Beat\nscheduler_tick · 5 s] --> Q{Atomic claim\nUPDATE WHERE QUEUED}
    Q -->|claimed| R[Worker Pool\nassign by language]
    R --> S[execute_pipeline_run\nCelery task]
    S -->|stage events| O
    O -->|poll /ui/bootstrap| T[Live Dashboard]
```

---

## File Structure

```text
Jenkins_Log_Intel_System/
├── main.py                          # FastAPI app factory, router mounting, lifespan
├── pyproject.toml                   # Dependencies, build config, pytest settings
│
├── app/
│   ├── config.py                    # Pydantic settings — env vars & secrets
│   ├── models.py                    # SQLAlchemy ORM: BuildEvent, SystemMetrics
│   ├── pipeline_models.py           # PipelineRun, RunStatus, StageExecution
│   ├── worker_models.py             # Worker, WorkerStatus, language enum
│   ├── tasks.py                     # process_build_failure — orchestrates full pipeline
│   ├── pipeline_tasks.py            # Stage simulation and event emission
│   ├── scheduler.py                 # Celery app + beat tasks (tick, arrival, drift)
│   │
│   ├── routers/
│   │   ├── webhook.py               # POST /webhook/jenkins — HMAC-verified ingestion
│   │   ├── github_webhook.py        # POST /webhook/github  — push event handler
│   │   ├── jobs.py                  # POST /jobs/trigger · GET /jobs · stage events
│   │   ├── workers.py               # GET /api/workers — pool status
│   │   └── ui.py                    # GET /ui/* — all dashboard data endpoints
│   │
│   ├── services/
│   │   ├── log_fetcher.py           # Jenkins REST client, retry, 10 MB truncation
│   │   ├── log_parser.py            # ANSI/timestamp strip, ErrorBlock extraction
│   │   ├── classifier.py            # YAML rule engine → FailureTag (category + confidence)
│   │   ├── root_cause.py            # LLM chain: Groq → Anthropic → template fallback
│   │   ├── notifier.py              # Slack Block Kit + HTML email delivery
│   │   ├── job_scheduler.py         # schedule_pipeline, dashboard snapshot
│   │   ├── worker_pool.py           # assign_worker, seed_workers, simulate_execution
│   │   ├── jenkinsfile_parser.py    # Fetch & parse Jenkinsfile from repo
│   │   └── pattern_store.py         # Historical failure patterns (read/write)
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_classifier.py
│       ├── test_log_parser.py
│       ├── test_job_scheduler.py
│       ├── test_jobs_router.py
│       ├── test_webhook.py
│       ├── test_jenkinsfile_parser.py
│       └── test_bug_fixes.py
│
├── frontend/
│   ├── index.html                   # Dashboard overview — live activity stream
│   ├── queue.html                   # Queue explorer
│   ├── scheduler.html               # Kanban + decision log
│   ├── workers.html                 # Worker pool monitor
│   ├── webhooks.html                # Webhook event log + payload generator
│   ├── backend.html                 # Backend console
│   ├── simulation.html              # Chaos + trigger controls
│   └── assets/app.js               # All UI logic — polling, rendering, empty states
│
└── rules/
    └── classifier_rules.yaml        # Regex failure rules: flaky_test · env_issue · dependency_error · build_config · infrastructure
```

---

## Failure Classification

Rules are defined in `rules/classifier_rules.yaml` and evaluated against every log line at runtime — no redeployment needed to add patterns.

| Category | Severity | Triggers |
| --- | --- | --- |
| `flaky_test` | P2 | `AssertionError`, `RERUN`, `test.*failed` |
| `env_issue` | P1 | `secret.*not.*found`, `permission denied`, `ENV` |
| `dependency_error` | P2 | `ModuleNotFoundError`, `npm ERR`, `Could not resolve` |
| `build_config` | P2 | `WorkflowScript.*error`, `Jenkinsfile`, `syntax error` |
| `infrastructure` | P1 | `OutOfMemoryError`, `OOM`, `No space left` |
| `unknown` | P3 | catch-all |

---

## Quickstart

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env with your Jenkins, database, Redis, Slack, and webhook values

# 3. Run API
uvicorn main:app --reload --port 8000

# 4. Run Celery worker + beat (optional — needed for background scheduling)
celery -A app.scheduler worker --loglevel=info --pool=solo &
celery -A app.scheduler beat   --loglevel=info

# 5. Open the dashboard
open http://localhost:8000

# 6. Run tests
pytest
```

---

## Local Setup (Redis, Celery, Slack)

For full real-time behaviour run Redis and Celery locally and provide a Slack bot token in `.env`.

**Start Redis:**

```bash
docker run --rm -p 6379:6379 --name redis-local redis:7
```

**Create venv and install deps:**

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

**Run all three services:**

```bash
# Terminal 1: API
uvicorn main:app --reload

# Terminal 2: Celery worker
celery -A app.scheduler worker --loglevel=info

# Terminal 3: Celery beat (scheduler tick every 5s)
celery -A app.scheduler beat --loglevel=info
```

---

## Webhook Testing with ngrok

To receive real GitHub or Jenkins webhooks locally, expose the API via ngrok:

```bash
# One-time setup
ngrok config add-authtoken YOUR_AUTH_TOKEN_HERE

# Start tunnel
ngrok start --config ngrok.yml --all
```

ngrok displays URLs like:

```text
api     -> http://localhost:8000    https://xxxx.ngrok-free.app
jenkins -> http://localhost:8080    https://xxxx.ngrok-free.app
```

Configure GitHub to send push events to `https://xxxx.ngrok-free.app/webhook/github`. Within 10 seconds of a push, the commit appears in the Live Activity Stream on the dashboard.

---

## API Reference

### Webhooks

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/webhook/jenkins` | Ingest Jenkins build result (HMAC-verified) |
| `POST` | `/webhook/jenkins/simulate` | Inject a synthetic Jenkins failure |
| `POST` | `/webhook/github` | Ingest GitHub push/PR event (HMAC-verified) |
| `POST` | `/webhook/github/simulate` | Inject a synthetic GitHub push |

### Jobs & Workers

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/jobs/trigger` | Manually trigger a pipeline run |
| `GET` | `/jobs` | Dashboard snapshot — runs grouped by status |
| `GET` | `/jobs/{run_id}` | Single run detail |
| `POST` | `/jobs/{run_id}/stage-event` | Emit a stage progress event |
| `GET` | `/api/workers` | Worker pool status |
| `GET` | `/api/workers/{worker_id}` | Single worker detail |

### Dashboard Data (UI endpoints)

| Method | Path | Purpose | Poll interval |
| --- | --- | --- | --- |
| `GET` | `/ui/bootstrap` | Full dashboard snapshot (health, workers, queue, activity stream) | 10 s |
| `GET` | `/ui/queue` | All pipeline runs by status | 5 s |
| `GET` | `/ui/scheduler` | Kanban data (queued, running, completed) | 5 s |
| `GET` | `/ui/build_events` | Latest Jenkins failure analysis records | 5 s |
| `GET` | `/ui/metrics/live` | Real-time CPU, memory, chaos intensity | 5 s |
| `GET` | `/ui/metrics/history` | Historical metrics for the last N minutes | on-demand |
| `POST` | `/ui/queue/flush` | Delete all queued runs | — |

### System

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe |

---

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `JENKINS_URL` | ✅ | Base URL of your Jenkins instance |
| `JENKINS_USER` | ✅ | Jenkins username |
| `JENKINS_TOKEN` | ✅ | Read-only API token |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | ✅ | Celery broker — default `redis://localhost:6379` |
| `SLACK_BOT_TOKEN` | ⬜ | Bot token for Slack alert delivery |
| `GROQ_API_KEY` | ⬜ | Primary LLM (Groq). Falls back to Anthropic if absent |
| `ANTHROPIC_API_KEY` | ⬜ | Secondary LLM fallback |
| `GITHUB_TOKEN` | ⬜ | For fetching Jenkinsfiles from private repos |
| `NGROK_URL` | ⬜ | Public URL shown in the Webhooks page |
| `JENKINS_WEBHOOK_SECRET` | ⬜ | HMAC secret — omit to disable Jenkins signature verification |
| `GITHUB_WEBHOOK_SECRET` | ⬜ | HMAC secret for GitHub webhook signature verification |

---

> Built for automated CI/CD triage. Not a substitute for fixing your flaky tests.
