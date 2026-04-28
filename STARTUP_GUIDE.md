# 🚀 Full Stack Setup & Launch Guide

## Prerequisites

### 1. ✅ Python Virtual Environment (Already Set Up)
```bash
# Verify .venv exists and is activated
D:\Jenkins_Log_Intel_System\.venv\Scripts\Activate.ps1
```

### 2. ⚙️ Redis Server (REQUIRED - Must Run First)

**Option A: Redis via Windows Subsystem for Linux (WSL)**
```bash
# In WSL terminal:
sudo service redis-server start
# or
redis-server
```

**Option B: Use Redis Docker**
```bash
# Run Redis in Docker (if Docker Desktop is installed)
docker run -d -p 6379:6379 redis:latest
```

**Option C: Redis Windows Binary**
- Download from: https://github.com/microsoftarchive/redis/releases
- Extract and run: `redis-server.exe`
- Runs on `localhost:6379`

**Verify Redis is Running:**
```bash
# In PowerShell, test Redis connection:
$socket = New-Object System.Net.Sockets.TcpClient
try {
    $socket.Connect('localhost', 6379)
    Write-Host "✓ Redis is running on port 6379"
} catch {
    Write-Host "✗ Redis is NOT running"
}
```

### 3. 🐘 PostgreSQL Database (REQUIRED)

**Option A: PostgreSQL Service (Windows)**
- Already running as Windows service (usually)
- Default: `postgresql+asyncpg://postgres:1234@localhost:5432/jenkins_log_intel`

**Option B: PostgreSQL Docker**
```bash
docker run -d \
  -e POSTGRES_PASSWORD=1234 \
  -e POSTGRES_DB=jenkins_log_intel \
  -p 5432:5432 \
  postgres:latest
```

**Verify Database Connection:**
```bash
# Test from PowerShell:
d:.venv\Scripts\python.exe -c "
from app.config import settings
print('✓ Database:', settings.DATABASE_URL)
"
```

### 4. 👷 Jenkins Master (Real Instance)
- Running on `http://localhost:8080`
- User: `admin`
- Token stored in `.env`

---

## Full Stack Startup (Step-by-Step)

### Step 1: Verify All Prerequisites

```bash
# Navigate to project
cd D:\Jenkins_Log_Intel_System

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Verify environment variables
python -c "from app.config import settings; print('✓ Config loaded')"

# Run tests (optional but recommended)
pytest -v --tb=short
```

**Expected Output:**
```
✓ Config loaded
======================== 69 passed, 1 warning in 1.70s ========================
```

### Step 2: Start FastAPI Server

**In Terminal 1:**
```bash
cd D:\Jenkins_Log_Intel_System
.\.venv\Scripts\Activate.ps1

# Start FastAPI with auto-reload on port 8001 (Jenkins is on 8080)
uvicorn main:app --reload --port 8001
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

**✓ Server Ready:** http://localhost:8001/docs (Swagger UI)
**⚠️ Note:** Jenkins runs on port 8080, FastAPI on port 8001 to avoid conflicts

### Step 3: Start Celery Worker

**In Terminal 2:**
```bash
cd D:\Jenkins_Log_Intel_System
.\.venv\Scripts\Activate.ps1

# Start Celery worker
# Note: Use --pool=solo on Windows to avoid multiprocessing issues
celery -A app.scheduler worker --loglevel=info --pool=solo
```

**Expected Output:**
```
 -------------- celery@HOSTNAME v5.3.x celery
 --- ***** -----
 -- ******* ---- Windows-10 CPU cores: 8
 - *** --- * --- eventlet: unavailable pool implementation: solo
  - ** ---------- [queues]
  - ** ---------- celery
  - ** ----------
  [Tasks]
    . app.scheduler.scheduler_tick
    . app.scheduler.random_job_arrival
    . app.scheduler.worker_load_drift
    ...
```

⚠️ **WARNING for Windows:** If you see `PermissionError`, use the `--pool=solo` flag:
```bash
celery -A app.scheduler worker --loglevel=info --pool=solo
```

### Step 4: Start Celery Beat (Scheduler)

**In Terminal 3:**
```bash
cd D:\Jenkins_Log_Intel_System
.\.venv\Scripts\Activate.ps1

# Start Celery Beat scheduler
celery -A app.scheduler beat --loglevel=info
```

**Expected Output:**
```
celery beat v5.3.x is starting.
LocalTime 2026-04-28 17:15:00.000000
LogFile-|-
MaxInterval-|-5.0s (scheduler: scheduler_tick)
```

⚠️ **Alternative:** Use `--scheduler=beat` if needed for Windows compatibility.

---

## System is Ready! 🎉

### Dashboard Access

```
🌐 Web Dashboard:  http://localhost:8001/jobs
📊 API Swagger:    http://localhost:8001/docs
⚙️ Jenkins:        http://localhost:8080
```

### Verify All Components

**Terminal 1 (FastAPI):** Should show periodic logs from webhook/API calls
**Terminal 2 (Worker):** Should show task execution logs
**Terminal 3 (Beat):** Should show scheduled task dispatch (every 5s, 15s, 45s)

---

## Test the Full System

### Option 1: Trigger Job via REST API

```bash
# In any terminal/PowerShell:

# Create a pipeline run
curl -X POST http://localhost:8001/jobs/trigger `
  -H "Content-Type: application/json" `
  -d '{
    "repo_url": "https://github.com/example/python-project",
    "branch": "main",
    "triggered_by": "manual"
  }'

# Expected Response:
# {
#   "run_id": 1,
#   "status": "QUEUED",
#   "jenkins_job_name": "example/python-project#main",
#   "stages": ["checkout", "install", "lint", "test", "build"],
#   "message": "Pipeline queued successfully"
# }
```

### Option 2: View Dashboard

Visit: **http://localhost:8001/jobs**

```json
{
  "QUEUED": [
    {
      "id": 1,
      "repo_url": "https://github.com/example/python-project",
      "branch": "main",
      "status": "QUEUED",
      "queued_at": "2026-04-28T17:15:00Z",
      "stages": [...]
    }
  ],
  "IN_PROGRESS": [
    {
      "id": 2,
      "repo_url": "https://github.com/another/node-project",
      "branch": "develop",
      "status": "IN_PROGRESS",
      "started_at": "2026-04-28T17:14:50Z",
      "stages": [...]
    }
  ],
  "COMPLETED": [
    {
      "id": 3,
      "status": "COMPLETED",
      "result": "SUCCESS",
      "duration_s": 425,
      "completed_at": "2026-04-28T17:10:00Z",
      "stages": [...]
    }
  ],
  "FAILED": []
}
```

### Option 3: Check Individual Run Status

```bash
# Get details of run ID 1
curl http://localhost:8001/jobs/1

# Expected Response:
# {
#   "id": 1,
#   "repo_url": "...",
#   "branch": "...",
#   "status": "IN_PROGRESS",
#   "jenkins_job_name": "...",
#   "jenkins_build_number": 42,
#   "jenkins_build_url": "http://localhost:8080/job/.../42/",
#   "stages": [
#     {
#       "name": "checkout",
#       "status": "SUCCESS",
#       "duration_s": 3
#     },
#     {
#       "name": "install",
#       "status": "RUNNING",
#       "duration_s": null
#     }
#   ],
#   "duration_s": 12
# }
```

---

## Troubleshooting

### ❌ Redis Connection Error
```
Cannot connect to redis://localhost:6379
```
**Solution:**
1. Start Redis first (see Prerequisites section)
2. Verify: `netstat -an | findstr 6379`
3. If not found, install and start Redis

### ❌ PostgreSQL Connection Error
```
could not connect to server: Connection refused
```
**Solution:**
1. Verify PostgreSQL service is running:
   ```bash
   Get-Service PostgreSQL* | Select-Object Status,Name
   ```
2. If not running, start it:
   ```bash
   # As Administrator
   net start postgresql-x64-14  # (adjust version number)
   ```

### ❌ Permission Denied (Celery on Windows)
```
PermissionError: [WinError 5] Access is denied
```
**Solution:**
Use `--pool=solo`:
```bash
celery -A app.scheduler worker --loglevel=info --pool=solo
```

### ❌ Address Already in Use (Port 8001)
```
Address already in use
```
**Solution:**
```bash
# Find and kill process on port 8001
netstat -ano | findstr :8001
taskkill /PID <PID> /F

# Or use different port:
uvicorn main:app --reload --port 8002
```

### ❌ ModuleNotFoundError
```
ModuleNotFoundError: No module named 'app'
```
**Solution:**
Make sure you're running from the project root directory:
```bash
cd D:\Jenkins_Log_Intel_System
pwd  # Should show: D:\Jenkins_Log_Intel_System
```

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│               Browser/Curl Client                       │
│  http://localhost:8000/jobs  (REST API)                │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────v──────────────┐
         │   FastAPI Server           │
         │   (Terminal 1)             │
         │   Port: 8001               │
         │   - Webhooks               │
         │   - REST API               │
         │   - Background tasks       │
         └──────────────┬──────────────┘
                       │
         ┌─────────────v──────────────────────┐
         │      Redis Message Broker          │
         │      (Separate Redis instance)     │
         │      localhost:6379                │
         └──────────────┬──────────────────────┘
                       │
         ┌─────────────v──────────────┐
         │  Celery Worker             │
         │  (Terminal 2)              │
         │  Processes tasks           │
         └──────────────┬──────────────┘
                       │
         ┌─────────────v──────────────┐
         │  Celery Beat Scheduler     │
         │  (Terminal 3)              │
         │  Dispatches jobs every 5s  │
         └──────────────┬──────────────┘
                       │
         ┌─────────────v──────────────────────┐
         │   PostgreSQL Database              │
         │   localhost:5432                   │
         │   - pipeline_runs                  │
         │   - stage_executions               │
         │   - worker_assignments             │
         └────────────────────────────────────┘
```

---

## Next Steps

1. **Start Redis** (if not running)
2. **Open Terminal 1:** Start FastAPI server (port 8001)
3. **Open Terminal 2:** Start Celery worker (with `--pool=solo` on Windows)
4. **Open Terminal 3:** Start Celery Beat
5. **Visit Dashboard:** http://localhost:8001/jobs
6. **Visit Jenkins:** http://localhost:8080 (real Jenkins instance)
6. **Trigger Jobs:** Use REST API or wait for simulated arrivals (every 45s)
7. **Monitor Logs:** Watch terminals 1-3 for real-time activity

---

## Performance Notes

- **Scheduler tick every 5 seconds:** Claims queued jobs, assigns workers, triggers Jenkins
- **Random job arrivals every 45 seconds:** Simulates external webhook/API triggers
- **Worker load drift every 15 seconds:** Simulates realistic system variability
- **Job queue:** FIFO (First-In-First-Out) with language-aware worker assignment
- **Worker pool:** 4 simulated workers with load balancing across Python/Node/Java

---

**✅ Ready to run! Start with Redis, then follow the 4 terminal startup sequence above.**
