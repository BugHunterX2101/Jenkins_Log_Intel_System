# Jenkins Log Intelligence Engine

A FastAPI service that intercepts Jenkins build failures, analyses logs with an LLM-backed root-cause engine, dispatches pipeline runs across a simulated worker pool, and fires Slack/email alerts — all autonomously.

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

    M([API · POST /jobs/trigger]) --> N[Job Scheduler\nschedule_pipeline]
    N --> O[(PostgreSQL\nPipelineRun · Worker)]
    P[Celery Beat\nscheduler_tick · 5 s] --> Q{Atomic claim\nUPDATE WHERE QUEUED}
    Q -->|claimed| R[Worker Pool\nassign by language]
    R --> S[execute_pipeline_run\nCelery task]
    S -->|stage events| O
    S --> T[Dashboard\nGET /jobs]

    U[random_job_arrival\n45 s] -->|synthetic load| N
    V[worker_load_drift\n15 s] --> O
```

---

## File Structure

```
Jenkins_Log_Intel_System/
├── main.py                          # FastAPI app factory, router mounting, lifespan
├── pyproject.toml                   # Dependencies, build config, pytest settings
│
├── app/
│   ├── config.py                    # Pydantic settings — env vars & secrets
│   ├── models.py                    # SQLAlchemy ORM base models
│   ├── pipeline_models.py           # PipelineRun, RunStatus, stage tracking
│   ├── worker_models.py             # Worker, WorkerStatus, language enum
│   ├── tasks.py                     # process_build_failure — orchestrates full pipeline
│   ├── pipeline_tasks.py            # Stage simulation and event emission
│   ├── scheduler.py                 # Celery app + beat tasks (tick, arrival, drift)
│   │
│   ├── routers/
│   │   ├── webhook.py               # POST /webhook/jenkins — HMAC-verified ingestion
│   │   ├── github_webhook.py        # POST /webhook/github  — push event handler
│   │   ├── jobs.py                  # POST /jobs/trigger · GET /jobs · stage events
│   │   └── workers.py               # GET /workers — pool status
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
└── rules/
    └── classifier_rules.yaml        # Regex failure rules: flaky_test · env_issue · dependency_error · build_config · infrastructure
```

---

## Failure Classification

Rules are defined in `rules/classifier_rules.yaml` and evaluated against every log line at runtime — no redeployment needed to add patterns.

| Category | Severity | Triggers |
|---|---|---|
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
cp .env.example .env   # set JENKINS_URL, DATABASE_URL, REDIS_URL, SLACK_BOT_TOKEN, etc.

# 3. Run API
uvicorn main:app --reload

# 4. Run Celery worker + beat
celery -A app.scheduler worker --loglevel=info &
celery -A app.scheduler beat   --loglevel=info

# 5. Test
pytest
```

## Local Setup (Redis, Celery, Slack)

For full real-time behavior run Redis and Celery locally and provide a Slack bot token in `.env`.

- Start Redis (recommended via Docker):

```bash
docker run --rm -p 6379:6379 --name redis-local redis:7
```

- Create and activate the project venv and install deps:

```bash
python -m venv .venv
.venv\Scripts\activate   # PowerShell/CMD on Windows
pip install -e ".[dev]"
```

- Provide a Slack bot token in `.env`:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
```

- Run the API and background workers in separate terminals:

```bash
# Terminal 1: API
uvicorn main:app --reload

# Terminal 2: Celery worker
celery -A app.scheduler worker --loglevel=info

# Terminal 3: Celery beat (scheduler)
celery -A app.scheduler beat --loglevel=info
```

With Redis + Celery running and `SLACK_BOT_TOKEN` set, notifications and task scheduling operate in real-time.

## Webhook Testing with ngrok

To test webhooks locally (e.g., from GitHub or Jenkins), use ngrok to expose your local API and Jenkins to the internet.

ngrok is already installed on Windows. To set up tunnels:

```bash
# 1. Create or retrieve your ngrok authtoken from https://dashboard.ngrok.com
#    (Optional — free tier works without it, but with rate limits)

# 2. Set the auth token (one-time setup):
ngrok config add-authtoken YOUR_AUTH_TOKEN_HERE

# 3. Start the tunnels (exposes both API and Jenkins):
ngrok start --config ngrok.yml --all
```

ngrok will display URLs like:

```
api -> http://localhost:8000                https://...ngrok-free.app
jenkins -> http://localhost:8080            https://...ngrok-free.app
```

Use the ngrok URLs in:

- **GitHub webhook**: Set the payload URL to `https://...ngrok-free.app/webhook/github`
- **Jenkins webhook**: Point to `https://...ngrok-free.app/webhook/jenkins`
- **External tests**: Call the dashboard at `https://...ngrok-free.app/jobs`

The tunnels stay active as long as the ngrok process runs. Each time you restart ngrok, you get new URLs.

**Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/webhook/jenkins` | Ingest Jenkins build result |
| `POST` | `/webhook/github` | Ingest GitHub push event |
| `POST` | `/jobs/trigger` | Manually trigger a pipeline run |
| `GET` | `/jobs` | Dashboard snapshot |
| `GET` | `/jobs/{run_id}` | Single run detail |
| `POST` | `/jobs/{run_id}/stage-event` | Emit stage progress |
| `GET` | `/workers` | Worker pool status |
| `GET` | `/health` | Liveness probe |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JENKINS_URL` | ✅ | Base URL of your Jenkins instance |
| `JENKINS_USER` | ✅ | Jenkins username |
| `JENKINS_TOKEN` | ✅ | Read-only API token |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` |
| `REDIS_URL` | ✅ | Celery broker, default `redis://localhost:6379` |
| `SLACK_BOT_TOKEN` | ✅ | Bot token for alert delivery |
| `GROQ_API_KEY` | ⬜ | Primary LLM (Groq). Falls back to Anthropic if absent |
| `ANTHROPIC_API_KEY` | ⬜ | Secondary LLM fallback |
| `GITHUB_TOKEN` | ⬜ | For fetching Jenkinsfiles from private repos |
| `JENKINS_WEBHOOK_SECRET` | ⬜ | HMAC secret — omit to disable signature verification |
| `GITHUB_WEBHOOK_SECRET` | ⬜ | HMAC secret for GitHub webhook signature verification |

---

> Built for automated CI/CD triage. Not a substitute for fixing your flaky tests.
