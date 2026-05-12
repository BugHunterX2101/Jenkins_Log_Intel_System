# Jenkins Log Intelligence Engine

A full-stack CI/CD intelligence platform built with **FastAPI** and **vanilla JS**. It receives real GitHub and Jenkins webhooks, analyses build failure logs with an LLM-backed root-cause engine, schedules pipeline runs across a language-aware worker pool, and streams live status to an 8-page real-time dashboard — with zero fake or simulated data.

---

## Dashboard

Eight live pages served at `http://localhost:8000`:

| Page | Path | What it shows |
| --- | --- | --- |
| **Overview** | `/` | Live activity stream, worker utilisation, queue depth, system health |
| **Queue** | `/queue` | Active pipeline runs, wait times, live queue depth chart, DB table sizes |
| **Scheduler** | `/scheduler` | Kanban board (Queued → Scheduled → Running → Completed), decision log, priority queue |
| **Workers** | `/workers` | Worker pool cards, language assignments, load timeline |
| **Webhooks** | `/webhooks` | Accepted events, live webhook event stream, endpoint configuration |
| **Backend Console** | `/backend` | API route health, live request feed, memory/CPU metrics |
| **Explorer** | `/explorer` | Full pipeline run history — filter by status, repo, branch, author |
| **Settings** | `/settings` | Environment variable status, scheduler preferences, worker pool breakdown |

Every panel polls live data from the backend — no hardcoded placeholder values or simulated data anywhere.

---

## Architecture

```mermaid
flowchart TD
    A([Jenkins Webhook]) -->|POST /webhook/jenkins\nHMAC-verified| B[Webhook Router]
    B -->|FINALIZED · FAILURE| C[Background Task\ntasks.py]

    C --> D[Log Fetcher\nJenkins REST API\n3× retry · 10 MB cap]
    D --> E[Log Parser\nANSI strip · error block\nextraction ±5 ctx lines]
    E --> F[Classifier\nregex rules YAML\nHIGH / MEDIUM / LOW]
    F --> G[Pattern Store\nTF-IDF similarity\nPostgreSQL]
    F & G --> H{LLM Root Cause\nAnalyser}

    H -->|primary| I[Groq API]
    H -->|fallback| J[Anthropic Claude]
    H -->|offline| K[Template Engine]

    I & J & K --> L[Notifier\nSlack Block Kit\nHTML email]

    M([GitHub Push / PR]) -->|POST /github-webhook/\nHMAC-verified| N[GitHub Webhook Router]
    N --> O[Job Scheduler\nschedule_pipeline\nJenkinsfile parse]
    O --> P[(PostgreSQL\nPipelineRun · StageExecution\nWorker · BuildEvent)]

    Q[Scheduler Loop\nevery 5s] -->|atomic claim| R[Worker Pool\nlanguage-aware routing]
    R -->|assigns worker| P
    P -->|stage-event callbacks| S[job_scheduler.py\non_stage_started\non_stage_completed\non_build_completed]
    S --> P

    P -->|poll /ui/bootstrap| T[Live Dashboard\n8 pages]
```

---

## How It Works

### GitHub → Pipeline Run

1. A push or pull-request event hits `POST /github-webhook/`
2. Signature verified via `GITHUB_WEBHOOK_SECRET`
3. Repo URL, branch, author, and commit SHA extracted from payload
4. Jenkinsfile fetched from the repo to discover pipeline stages
5. A `PipelineRun` record created (status: `QUEUED`) with one `StageExecution` per stage
6. The 5-second scheduler loop atomically claims the run, assigns it to the best-fit worker by language, and marks it `IN_PROGRESS`
7. Jenkins runs the actual build; stage progress arrives via `POST /jobs/{run_id}/stage-event`
8. On completion the run is marked `COMPLETED` or `FAILED` and the worker is released

### Jenkins Failure → Alert

1. Jenkins sends `POST /webhook/jenkins` when a build finalises with `FAILURE`
2. Console log fetched from Jenkins API (3 retries, 10 MB cap)
3. Log parsed into error blocks; classified against `rules/classifier_rules.yaml`
4. Historical similar failures looked up via TF-IDF cosine similarity
5. LLM generates a plain-English root-cause summary and fix suggestions (Groq → Anthropic → template fallback)
6. Analysis stored as a `BuildEvent`; Slack notification sent

### Branch Priority Scheduling

| Branch pattern | Priority |
| --- | --- |
| `hotfix/*` | P1 — dispatched first |
| `main` / `master` | P2 |
| `release/*` | P3 |
| `develop` | P4 |
| `feature/*` | P5 |
| anything else | P6 |

---

## File Structure

```text
Jenkins_Log_Intel_System/
├── main.py                          # FastAPI app factory, router mounting, lifespan
├── pyproject.toml                   # Dependencies, build config, pytest settings
│
├── app/
│   ├── config.py                    # Pydantic settings — all env vars & secrets
│   ├── db.py                        # Async SQLAlchemy engine + session factory
│   ├── models.py                    # ORM: BuildEvent, SystemMetrics, PatternRecord
│   ├── pipeline_models.py           # PipelineRun, RunStatus, StageExecution
│   ├── worker_models.py             # Worker, WorkerAssignment, WorkerStatus, WorkerLanguage
│   ├── tasks.py                     # process_build_failure — full Jenkins failure pipeline
│   ├── pipeline_tasks.py            # Celery tasks: trigger_jenkins_build, poll_pipeline_stages
│   ├── scheduler.py                 # Scheduler loop (5 s tick), Celery beat tasks
│   │
│   ├── routers/
│   │   ├── webhook.py               # POST /webhook/jenkins — HMAC-verified ingestion
│   │   ├── github_webhook.py        # POST /github-webhook/ — push + PR handler
│   │   ├── jobs.py                  # POST /jobs/trigger · GET /jobs · stage events
│   │   ├── workers.py               # GET /api/workers — pool status, online/offline control
│   │   └── ui.py                    # GET /ui/* — all dashboard data endpoints
│   │
│   ├── services/
│   │   ├── log_fetcher.py           # Jenkins REST client, retry, 10 MB truncation
│   │   ├── log_parser.py            # ANSI/timestamp strip, ErrorBlock extraction
│   │   ├── classifier.py            # YAML rule engine → FailureTag (category + confidence)
│   │   ├── root_cause.py            # LLM chain: Groq → Anthropic → template fallback
│   │   ├── notifier.py              # Slack Block Kit + HTML email delivery
│   │   ├── job_scheduler.py         # schedule_pipeline, stage lifecycle callbacks
│   │   ├── worker_pool.py           # assign_worker, release_worker, language detection
│   │   ├── jenkinsfile_parser.py    # Fetch & parse Jenkinsfile stage names from repo
│   │   └── pattern_store.py         # TF-IDF historical failure pattern matching
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
│   ├── queue.html                   # Queue explorer — active runs + depth chart
│   ├── scheduler.html               # Kanban + priority queue + decision log
│   ├── workers.html                 # Worker fleet monitor
│   ├── webhooks.html                # Webhook event log + GitHub setup guide
│   ├── backend.html                 # Backend console — metrics, request feed
│   ├── explorer.html                # Full pipeline run history with filters
│   ├── settings.html                # System settings + env var status
│   └── assets/
│       ├── app.js                   # All UI logic — polling, rendering, empty states
│       └── styles.css               # CSS custom properties (bar-fill, animations)
│
├── rules/
│   └── classifier_rules.yaml        # Regex failure rules (add patterns here, no redeployment)
│
└── scripts/
    └── reset_db.py                  # One-shot script: wipe all pipeline data, reset workers
```

---

## Failure Classification

Rules live in `rules/classifier_rules.yaml` and are evaluated against every log line at runtime — adding a new pattern requires no redeployment.

| Category | Severity | Example triggers |
| --- | --- | --- |
| `flaky_test` | P2 | `AssertionError`, `RERUN`, `test.*failed` |
| `env_issue` | P1 | `secret.*not.*found`, `permission denied`, missing env vars |
| `dependency_error` | P2 | `ModuleNotFoundError`, `npm ERR`, `Could not resolve` |
| `build_config` | P2 | `WorkflowScript.*error`, `Jenkinsfile`, `syntax error` |
| `infrastructure` | P1 | `OutOfMemoryError`, `OOM`, `No space left on device` |
| `unknown` | P3 | catch-all for unclassified failures |

---

## Quickstart

```bash
# 1. Create virtualenv and install
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env — fill in DATABASE_URL, REDIS_URL, GROQ_API_KEY, GITHUB_WEBHOOK_SECRET, etc.

# 3. Start PostgreSQL (if not already running)
# Ensure DATABASE_URL in .env points to your PostgreSQL instance

# 4. Run Redis (broker for Celery)
docker run --rm -p 6379:6379 redis:7

# 5. Start the API  (creates DB tables automatically on first run)
uvicorn main:app --reload --port 8000

# 6. (Optional) Start Celery for background Jenkins build triggering
celery -A app.scheduler worker --loglevel=info --pool=solo &
celery -A app.scheduler beat   --loglevel=info

# 7. Open the dashboard
open http://localhost:8000

# 8. Run tests
pytest
```

> The scheduler loop runs **inside the FastAPI process** every 5 seconds without Celery. Celery is only needed to trigger actual Jenkins builds via the Jenkins API.

---

## Receive Real GitHub Webhooks (ngrok)

To receive live push/PR events from GitHub on a local machine:

```bash
# Install ngrok and authenticate
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Expose the API
ngrok http 8000
```

ngrok prints a public URL like `https://xxxx.ngrok-free.app`. In GitHub:

1. Go to **Repository → Settings → Webhooks → Add webhook**
2. **Payload URL:** `https://xxxx.ngrok-free.app/github-webhook/`
3. **Content type:** `application/json`
4. **Secret:** value of `GITHUB_WEBHOOK_SECRET` in your `.env`
5. **Events:** _Pushes_ and _Pull requests_

The Webhooks page (`/webhooks`) shows the exact URL and setup guide.

---

## Reset the Database

To wipe all pipeline runs, build events, and metrics (workers are preserved):

```bash
python scripts/reset_db.py
```

---

## API Reference

### Webhooks (inbound)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/webhook/jenkins` | Ingest Jenkins build result — HMAC via `JENKINS_WEBHOOK_SECRET` |
| `POST` | `/webhook/github` | Ingest GitHub push/PR event — HMAC via `GITHUB_WEBHOOK_SECRET` |
| `POST` | `/github-webhook/` | Alias — use this as the GitHub Payload URL |

### Jobs & Workers

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/jobs/trigger` | Manually enqueue a pipeline run |
| `GET` | `/jobs` | Dashboard snapshot — runs grouped by status |
| `GET` | `/jobs/{run_id}` | Single run detail with stage breakdown |
| `POST` | `/jobs/{run_id}/stage-event` | Receive a stage progress callback from Jenkins |
| `GET` | `/api/workers` | Worker pool status + summary |
| `GET` | `/api/workers/{id}` | Single worker detail + recent assignments |
| `POST` | `/api/workers/{id}/offline` | Take a worker offline |
| `POST` | `/api/workers/{id}/online` | Bring a worker back online |

### Dashboard Data (`/ui/*`)

| Method | Path | Purpose | Frontend poll |
| --- | --- | --- | --- |
| `GET` | `/ui/bootstrap` | Full snapshot: health, workers, queue, activity stream, build events | 10 s |
| `GET` | `/ui/queue` | All pipeline runs grouped by status | 5 s |
| `GET` | `/ui/scheduler` | Kanban data: queued, scheduled, running, completed | 5 s |
| `GET` | `/ui/scheduler/mode` | Current routing mode (FIFO / Priority / Load-Balanced) | on-change |
| `POST` | `/ui/scheduler/mode` | Set routing mode | — |
| `GET` | `/ui/priority-queue` | QUEUED runs in dispatch order with wait times | 5 s |
| `GET` | `/ui/build_events` | Latest Jenkins failure analyses | 5 s |
| `GET` | `/ui/metrics/live` | Real-time CPU, memory, uptime, chaos intensity | 5 s |
| `GET` | `/ui/metrics/history` | Historical metric samples (`?period_minutes=60`) | 30 s |
| `GET` | `/ui/repositories` | Pipeline runs grouped by repo + branch | 10 s |
| `GET` | `/ui/webhook-config` | Webhook endpoint URL + secret hint | on-load |
| `GET` | `/ui/config-status` | Which env vars are configured (non-empty) | on-load |
| `POST` | `/ui/queue/{id}/cancel` | Abort an active or queued run | — |
| `POST` | `/ui/queue/flush` | Delete all QUEUED runs | — |

### System

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe — returns `{"status":"ok","version":"..."}` |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

---

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | ✅ | Celery broker — default `redis://localhost:6379` |
| `JENKINS_URL` | ✅ | Base URL of your Jenkins instance |
| `JENKINS_USER` | ✅ | Jenkins username |
| `JENKINS_TOKEN` | ✅ | Jenkins read-only API token |
| `GROQ_API_KEY` | ⬜ | Primary LLM (Groq). Falls back to Anthropic if absent |
| `ANTHROPIC_API_KEY` | ⬜ | Secondary LLM fallback |
| `SLACK_BOT_TOKEN` | ⬜ | Slack bot token for alert delivery |
| `SLACK_DEFAULT_CHANNEL` | ⬜ | Target Slack channel (default: `#build-alerts`) |
| `GITHUB_TOKEN` | ⬜ | Personal access token for fetching Jenkinsfiles from private repos |
| `GITHUB_WEBHOOK_SECRET` | ⬜ | HMAC secret for GitHub webhook signature verification |
| `JENKINS_WEBHOOK_SECRET` | ⬜ | HMAC secret for Jenkins webhook signature verification |
| `SENDER_EMAIL` | ⬜ | From address for email notifications |
| `MAX_CONCURRENT_EXECUTIONS` | ⬜ | Max parallel scheduler threads in FastAPI process (default: `6`) |

---

> Built for real-world CI/CD triage. All data shown in the dashboard comes from your actual GitHub pushes and Jenkins build results — nothing is simulated.
