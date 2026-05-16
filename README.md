# Jenkins Log Intelligence Engine

A full-stack CI/CD intelligence platform built with **FastAPI** and **vanilla JS**. It receives real GitHub and Jenkins webhooks, analyses build failure logs with an LLM-backed root-cause engine, schedules pipeline runs across a language-aware worker pool, and streams live status to a 9-page real-time dashboard — with zero fake or simulated data.

---

## Dashboard

Nine live pages served at `http://localhost:8000`:

| Page | Path | What it shows |
| --- | --- | --- |
| **Overview** | `/` | Live activity stream, worker utilisation, queue depth, system health |
| **Queue** | `/queue` | Active pipeline runs, human-readable wait times, live queue depth chart |
| **Scheduler** | `/scheduler` | Kanban board (Queued → In Progress → Completed), decision log, priority queue |
| **Workers** | `/workers` | Worker pool cards, language assignments, load timeline |
| **Webhooks** | `/webhooks` | Accepted events, LLM failure analysis panel, live event stream |
| **Analytics** | `/analytics` | Failure trends (30 days), failure-type breakdown, top failing jobs |
| **Backend Console** | `/backend` | API route health, live request feed, memory/CPU metrics |
| **Explorer** | `/explorer` | Full pipeline run history — filter by status, repo, branch, author |
| **Settings** | `/settings` | Environment variable status, scheduler preferences, worker pool breakdown |

Every panel is updated in real time — no hardcoded placeholder values or simulated data anywhere.

---

## Architecture

```mermaid
flowchart TD
    A([Jenkins Webhook]) -->|POST /webhook/jenkins\nHMAC-verified| B[Webhook Router]
    B -->|FINALIZED · FAILURE| C[Background Task\ntasks.py]

    C --> D[Log Fetcher\nJenkins REST API\n3× retry · 10 MB cap]
    D --> E[Log Parser\nANSI strip · ALL error blocks\n±5 ctx lines each]
    E --> F[Classifier\nregex rules YAML\nHIGH / MEDIUM / LOW]
    F --> G[Pattern Store\nTF-IDF similarity\nPostgreSQL]
    F & G --> H{LLM Root Cause\nAnalyser\n16 000-char full log}

    H -->|primary| I[Groq API\nllama-3.3-70b]
    H -->|fallback| J[Anthropic Claude]
    H -->|offline| K[Template Engine]

    I & J & K --> L[Notifier\nSlack Block Kit · 1500-char log\nHTML email]

    M([GitHub Push / PR]) -->|POST /github-webhook/\nHMAC-verified| N[GitHub Webhook Router]
    N --> O[Job Scheduler\nschedule_pipeline\nJenkinsfile parse]
    O --> P[(PostgreSQL\nPipelineRun · StageExecution\nWorker · BuildEvent)]

    Q[Scheduler Loop\nevery 5s] -->|atomic claim| R[Worker Pool\nlanguage-aware routing]
    R -->|assigns worker| S[_run_execution\nreal Jenkins trigger\npoll wfapi every 10s]
    S -->|build number + URL| P
    S -->|on FAILURE| C

    P -->|stage-event callbacks| T[job_scheduler.py\non_build_completed\n→ LLM analysis thread]
    T -->|non-SUCCESS| C
    T --> P

    P -->|SSE /ui/stream| U[Live Dashboard\n9 pages]
    P -->|REST polling| U
```

---

## How It Works

### GitHub → Pipeline Run

1. A push or pull-request event hits `POST /github-webhook/`
2. Signature verified via `GITHUB_WEBHOOK_SECRET`
3. Repo URL, branch, author, and commit SHA extracted from payload
4. Jenkinsfile fetched from the repo (using `GITHUB_TOKEN` for private repos) to discover real pipeline stages
5. A `PipelineRun` record created (status: `QUEUED`) with one `StageExecution` per stage
6. The 5-second scheduler loop atomically claims the run, assigns it to the best-fit worker by language, and marks it `IN_PROGRESS`
7. A real Jenkins build is triggered via the Jenkins REST API; the real build number and URL are persisted on the run
8. Jenkins wfapi is polled every 10 s for stage progress — stages update from PENDING → RUNNING → SUCCESS/FAILED
9. On completion the run is marked `COMPLETED` or `FAILED`, the worker is released, and LLM analysis is automatically triggered for failures

### Jenkins Failure → LLM Analysis → Slack

The analysis pipeline is triggered from **two independent paths** (with a duplicate guard so only one Slack message is ever sent per build):

- **Webhook path** — Jenkins `POST /webhook/jenkins` with `phase=FINALIZED, status=FAILURE`
- **Scheduler path** — `on_build_completed()` fires a daemon thread for every non-SUCCESS result

Once triggered, `_process_async` runs the full pipeline:

1. Fetch the **entire** console log from Jenkins API (up to 10 MB, 3-retry)
2. Parse **all** error blocks from the full log (each block: anchor line ± 5 context lines)
3. Append the last 4 000 chars of raw output (catches terminal errors without ERROR keywords)
4. Classify errors against `rules/classifier_rules.yaml` → category + confidence
5. Look up historically similar failures via TF-IDF cosine similarity
6. Send up to **16 000 chars** of log context to the LLM for root-cause analysis
7. LLM produces a summary that cites the exact error message, command, file, or package — not a generic category label
8. Store `BuildEvent` in PostgreSQL; send Slack Block Kit message with 1 500-char error excerpt, root cause, and 3 specific fix suggestions

### Branch Priority Scheduling

| Branch pattern | Priority |
| --- | --- |
| `hotfix/*` | P1 — dispatched first |
| `main` / `master` | P2 |
| `release/*` | P3 |
| `develop` | P4 |
| `feature/*` | P5 |
| anything else | P6 |

### Pipeline Auto-Retry

Transient infrastructure failures (`infrastructure`, `env_issue` categories) are automatically re-queued with exponential backoff:

| Attempt | Delay |
| --- | --- |
| 1st retry | 60 s |
| 2nd retry | 300 s (5 min) |

Configurable via `PIPELINE_MAX_RETRIES` and `PIPELINE_RETRY_BACKOFF_SECONDS`. Manual retry is also available via `POST /jobs/{run_id}/retry`.

---

## File Structure

```text
Jenkins_Log_Intel_System/
├── main.py                          # FastAPI app factory, router mounting, lifespan, SSE scheduler loop
├── pyproject.toml                   # Dependencies, build config, pytest settings
│
├── app/
│   ├── config.py                    # Pydantic settings — all env vars & secrets
│   ├── db.py                        # Async SQLAlchemy engine + session factory
│   ├── models.py                    # ORM: BuildEvent, SystemMetrics, PatternRecord
│   ├── pipeline_models.py           # PipelineRun, StageExecution (+ retry_count, max_retries, retry_after)
│   ├── worker_models.py             # Worker, WorkerAssignment, WorkerStatus, WorkerLanguage
│   ├── tasks.py                     # _process_async — full Jenkins failure pipeline (full-log LLM)
│   ├── pipeline_tasks.py            # Celery tasks: trigger_jenkins_build, poll_pipeline_stages
│   ├── scheduler.py                 # 5s tick loop, SSE broadcast, _run_execution (real Jenkins), Phase-6 retry
│   │
│   ├── routers/
│   │   ├── webhook.py               # POST /webhook/jenkins — HMAC-verified ingestion
│   │   ├── github_webhook.py        # POST /github-webhook/ — push + PR handler
│   │   ├── jobs.py                  # POST /jobs/trigger · GET /jobs · POST /jobs/{id}/retry
│   │   ├── workers.py               # GET /api/workers — pool status, online/offline control
│   │   └── ui.py                    # GET /ui/* — dashboard data + SSE stream + analytics
│   │
│   ├── services/
│   │   ├── log_fetcher.py           # Jenkins REST client, 3-retry, 10 MB truncation
│   │   ├── log_parser.py            # ANSI/timestamp strip, ErrorBlock extraction (all blocks)
│   │   ├── classifier.py            # YAML rule engine → FailureTag (category + confidence)
│   │   ├── root_cause.py            # LLM chain: Groq → Anthropic → template; 16k-char context
│   │   ├── notifier.py              # Slack Block Kit (1500-char log excerpt) + HTML email
│   │   ├── job_scheduler.py         # schedule_pipeline, stage callbacks, LLM trigger on failure
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
│   ├── queue.html                   # Queue explorer — active runs + human-readable wait times
│   ├── scheduler.html               # Kanban + priority queue + decision log
│   ├── workers.html                 # Worker fleet monitor
│   ├── webhooks.html                # Webhook event log + LLM failure analysis panel
│   ├── analytics.html               # Failure trends, type breakdown, top failing jobs (Chart.js)
│   ├── backend.html                 # Backend console — metrics, request feed
│   ├── explorer.html                # Full pipeline run history with filters
│   ├── settings.html                # System settings + env var status
│   └── assets/
│       ├── app.js                   # All UI logic — SSE, polling, rendering, formatWait()
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
# Edit .env — fill in DATABASE_URL, REDIS_URL, JENKINS_URL/USER/TOKEN,
# GROQ_API_KEY, SLACK_BOT_TOKEN, GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET, etc.

# 3. Start PostgreSQL (if not already running)
# Ensure DATABASE_URL in .env points to your PostgreSQL instance

# 4. Run Redis (broker for Celery)
docker run --rm -p 6379:6379 redis:7

# 5. Start the API  (creates DB tables + adds any missing columns automatically)
uvicorn main:app --port 8000

# 6. Start 4 Celery workers + beat (for parallel Jenkins build dispatch)
#    On Windows use --pool=solo; on Linux/macOS --pool=prefork works too.
celery -A app.scheduler.celery_app worker --pool=solo --hostname=worker1@%h --loglevel=info &
celery -A app.scheduler.celery_app worker --pool=solo --hostname=worker2@%h --loglevel=info &
celery -A app.scheduler.celery_app worker --pool=solo --hostname=worker3@%h --loglevel=info &
celery -A app.scheduler.celery_app worker --pool=solo --hostname=worker4@%h --loglevel=info &
celery -A app.scheduler.celery_app beat --loglevel=info &

# 7. Open the dashboard
open http://localhost:8000

# 8. Run tests
pytest
```

> The scheduler loop runs **inside the FastAPI process** every 5 seconds and dispatches real Jenkins builds without Celery. Celery workers increase throughput when many pipelines are queued concurrently.

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
| `POST` | `/jobs/{run_id}/retry` | Manually retry a FAILED run (respects `max_retries`) |
| `POST` | `/jobs/{run_id}/stage-event` | Receive a stage progress callback from Jenkins |
| `GET` | `/api/workers` | Worker pool status + summary |
| `GET` | `/api/workers/{id}` | Single worker detail + recent assignments |
| `POST` | `/api/workers/{id}/offline` | Take a worker offline |
| `POST` | `/api/workers/{id}/online` | Bring a worker back online |
| `POST` | `/api/workers/{id}/reset` | Force-reset a stuck BUSY worker to IDLE |
| `POST` | `/api/workers/recover` | Bulk-recover all stale workers |

### Dashboard Data (`/ui/*`)

| Method | Path | Purpose | Frontend poll |
| --- | --- | --- | --- |
| `GET` | `/ui/stream` | SSE stream — pushes `metrics` + `queue_snapshot` events every 5 s | persistent |
| `GET` | `/ui/bootstrap` | Full snapshot: health, workers, queue, activity stream, build events | 10 s |
| `GET` | `/ui/queue` | All pipeline runs grouped by status | 5 s |
| `GET` | `/ui/scheduler` | Kanban data: queued, scheduled, running, completed | 5 s |
| `GET` | `/ui/scheduler/mode` | Current routing mode (FIFO / Priority / Load-Balanced) | on-change |
| `POST` | `/ui/scheduler/mode` | Set routing mode | — |
| `GET` | `/ui/priority-queue` | QUEUED runs in dispatch order with wait times | 5 s |
| `GET` | `/ui/build_events` | Latest Jenkins failure analyses | 5 s |
| `GET` | `/ui/analytics` | Failure trends, type distribution, top failing jobs (30 days) | 60 s |
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
| `JENKINS_TOKEN` | ✅ | Jenkins API token |
| `GROQ_API_KEY` | ⬜ | Primary LLM (Groq llama-3.3-70b). Falls back to Anthropic if absent |
| `ANTHROPIC_API_KEY` | ⬜ | Secondary LLM fallback |
| `SLACK_BOT_TOKEN` | ⬜ | Slack bot token for failure alert delivery |
| `SLACK_DEFAULT_CHANNEL` | ⬜ | Target Slack channel (default: `#build-alerts`) |
| `GITHUB_TOKEN` | ⬜ | Personal access token for fetching Jenkinsfiles from private repos |
| `GITHUB_WEBHOOK_SECRET` | ⬜ | HMAC secret for GitHub webhook signature verification |
| `JENKINS_WEBHOOK_SECRET` | ⬜ | HMAC secret for Jenkins webhook signature verification |
| `SENDER_EMAIL` | ⬜ | From address for email notifications |
| `MAX_CONCURRENT_EXECUTIONS` | ⬜ | Max parallel scheduler threads in FastAPI process (default: `6`) |
| `WORKER_HEARTBEAT_TIMEOUT_MINUTES` | ⬜ | Minutes before a silent BUSY worker is auto-recovered (default: `30`) |
| `PIPELINE_MAX_RETRIES` | ⬜ | Auto-retry limit for infrastructure failures (default: `2`) |
| `PIPELINE_RETRY_BACKOFF_SECONDS` | ⬜ | Backoff delays per retry attempt (default: `[60, 300]`) |
| `ALLOW_SYNTHETIC_PIPELINE_STAGES` | ⬜ | Allow fallback stage names when no Jenkinsfile found (default: `false`) |
| `AUTO_SEED_WORKERS` | ⬜ | Seed default worker pool on startup (default: `false`) |
| `NGROK_API_URL` | ⬜ | ngrok management API URL for auto-detecting public tunnel (default: `http://localhost:4040`) |

---

> Built for real-world CI/CD triage. All data shown in the dashboard comes from your actual GitHub pushes and Jenkins build results — nothing is simulated or mocked.
