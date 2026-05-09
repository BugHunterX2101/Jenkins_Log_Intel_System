"""End-to-end smoke test — verifies every frontend/backend wiring point."""
import hashlib
import hmac
import json
import sys
import urllib.request

from app.config import settings

BASE = "http://localhost:8000"
PASS = "PASS"
FAIL = "FAIL"
results = []

def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            status = r.status
            body = r.read()
            try: return status, json.loads(body)
            except: return status, {}          # HTML page — just return status
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

def post(path, data=None, headers=None):
    body = json.dumps(data or {}).encode()
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(BASE + path, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status = r.status
            body = r.read()
            try: return status, json.loads(body)
            except: return status, {}
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

def check(label, ok, detail=""):
    sym = PASS if ok else FAIL
    results.append((sym, label, detail))
    print(f"  {sym} {label}" + (f"  [{detail}]" if detail else ""))

# ── HTML pages ──────────────────────────────────────────────────────────────
print("\n### HTML PAGES (9 routes) ###")
for page in ["/", "/backend", "/queue", "/scheduler",
             "/webhooks", "/workers", "/explorer", "/settings"]:
    s, _ = get(page)
    check(page, s == 200, f"HTTP {s}")

# ── Core read endpoints ──────────────────────────────────────────────────────
print("\n### CORE READ ENDPOINTS ###")

s, d = get("/health")
check("/health", s == 200 and d.get("status") == "ok", d.get("status", ""))

# /ui/bootstrap — feeds index, backend, queue, workers panels
s, d = get("/ui/bootstrap")
check("/ui/bootstrap", s == 200, f"{len(d)} top-level keys")
h = d.get("health", {}); q = d.get("queue", {})
w = d.get("workers", {}); db = q.get("database", {})
check("  health.chaos_intensity in (0,1]", 0 <= h.get("chaos_intensity", 1.0) <= 1.0,
    str(round(h.get("chaos_intensity", 0) * 100)) + "%")
check("  queue has queued + in_progress", {"queued","in_progress"}.issubset(q))
check("  queue.database has total_records/file_size/tables",
      {"total_records","file_size","tables"}.issubset(db))
check("  workers.items all have capabilities",
    all("capabilities" in ww for ww in w.get("items", [])), f"{len(w.get('items',[]))} workers")
check("  activity_stream is list", isinstance(d.get("activity_stream"), list),
      f"{len(d.get('activity_stream',[]))} items")
check("  backend_routes == 4", len(d.get("backend_routes", [])) == 4)
check("  backend.status present", "status" in d.get("backend", {}))
check("  backend.uptime present", "uptime" in d.get("backend", {}))
check("  backend.memory_used is int", isinstance(d.get("backend", {}).get("memory_used"), int))
check("  backend.cpu_percent present", "cpu_percent" in d.get("backend", {}))

# /ui/queue — feeds queue page table + metrics
s, d = get("/ui/queue")
check("/ui/queue", s == 200)
rbs = d.get("runs_by_status", {})
check("  5 status buckets", set(rbs.keys()) == {"QUEUED","IN_PROGRESS","COMPLETED","FAILED","ABORTED"})
sample = next((r for runs in rbs.values() for r in runs), None)
if sample:
    check("  run has id/repo/branch/status/queued_at",
          {"id","repo","branch","status","queued_at"}.issubset(sample))

# /ui/scheduler — feeds kanban + decision log
s, d = get("/ui/scheduler")
check("/ui/scheduler", s == 200)
check("  has queued/scheduled/running/completed",
      {"queued","scheduled","running","completed"}.issubset(d))
if d.get("running"):
    r = d["running"][0]
    check("  running item fields", {"id","repo","branch","job_name","started","duration_s","summary","priority"}.issubset(r))
if d.get("completed"):
    c = d["completed"][0]
    check("  completed item has completed/duration_s", {"completed","duration_s"}.issubset(c))

# /ui/build_events — feeds webhook events table + LLM analysis panel
s, d = get("/ui/build_events")
check("/ui/build_events", s == 200)
evts = d.get("events", [])
check("  returns events list", isinstance(evts, list), f"{len(evts)} events")
if evts:
    e = evts[0]
    check("  event_type present", "event_type" in e, e.get("event_type", ""))
    check("  repo_name present", "repo_name" in e, e.get("repo_name", ""))
    check("  delivery_id present", "delivery_id" in e, e.get("delivery_id", ""))
    check("  delivery_status not PENDING", e.get("delivery_status") != "PENDING",
          e.get("delivery_status", ""))
    check("  fix_suggestions is list", isinstance(e.get("fix_suggestions"), list))
    check("  summary_text present", bool(e.get("summary_text")))

# /ui/metrics/live — feeds backend-cpu, chaos dial, memory bar
s, d = get("/ui/metrics/live")
check("/ui/metrics/live", s == 200 and d.get("status") == "ok")
data = d.get("data", {})
check("  chaos_intensity < 100", data.get("chaos_intensity", 100) < 100,
      str(data.get("chaos_intensity")))
check("  queue_pressure uses active formula",
      data.get("queue_pressure", 9999) < data.get("queue_total", 0),
      f"pressure={data.get('queue_pressure')} total={data.get('queue_total')}")
check("  uptime_formatted present", bool(data.get("uptime_formatted")), data.get("uptime_formatted", ""))
check("  memory_used_bytes is int", isinstance(data.get("memory_used_bytes"), int))
check("  cpu_percent present", "cpu_percent" in data)

# /api/workers — feeds workers page cards + assignment table
s, d = get("/api/workers")
check("/api/workers", s == 200)
workers = d.get("workers", [])
check("  workers list non-empty", len(workers) > 0, f"{len(workers)} workers")
if workers:
    w = workers[0]
    check("  worker has id/name/language/status/load", {"id","name","language","status","load"}.issubset(w))
    check("  worker has capabilities field", "capabilities" in w, str(w.get("capabilities", ""))[:30])
    check("  worker has jobs_run/current_job", {"jobs_run","current_job"}.issubset(w))

s, d = get("/api/workers/1")
check("/api/workers/1 detail", s == 200)
check("  has recent_assignments list", isinstance(d.get("recent_assignments"), list))
check("  capabilities not duplicated", list(d.keys()).count("capabilities") == 1,
      f"count={list(d.keys()).count('capabilities')}")

# /jobs endpoints
s, d = get("/jobs")
check("/jobs dashboard", s == 200)
check("  has 5 status buckets", {"QUEUED","IN_PROGRESS","COMPLETED","FAILED","ABORTED"}.issubset(d))

s, _ = get("/jobs/dashboard")
check("/jobs/dashboard alias", s == 200, f"HTTP {s}")

s, _ = get("/jobs/1")
check("/jobs/1 int constraint", s in (200, 404), f"HTTP {s} (not 422)")

s, d = get("/ui/scheduler/mode")
check("/ui/scheduler/mode", s == 200, d.get("mode", ""))

# ── Write endpoints ──────────────────────────────────────────────────────────
print("\n### WRITE ENDPOINTS ###")

github_payload = {
    "ref": "refs/heads/main",
    "after": "abc123def4567890abc123def4567890abc123de",
    "repository": {
        "name": "pipeline-engine",
        "full_name": "acme/pipeline-engine",
        "clone_url": "https://github.com/acme/pipeline-engine.git",
        "html_url": "https://github.com/acme/pipeline-engine",
    },
    "pusher": {"name": "smoke-bot"},
    "head_commit": {"id": "abc123def4567890abc123def4567890abc123de"},
}
github_body = json.dumps(github_payload).encode()
github_headers = {"X-GitHub-Event": "push"}
if settings.GITHUB_WEBHOOK_SECRET:
    github_headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(), github_body, hashlib.sha256
    ).hexdigest()
s, d = post("/github-webhook/", github_payload, headers=github_headers)
check("POST /github-webhook/", s == 200, str(d.get("repo", "")))
check("  received real webhook", d.get("received") is True)

jenkins_payload = {
    "build": {
        "number": 12847,
        "phase": "FINALIZED",
        "status": "FAILURE",
        "url": "http://jenkins.example/job/backend-tests/12847/",
        "result": "FAILURE",
    }
}
jenkins_body = json.dumps(jenkins_payload).encode()
jenkins_headers = {}
if settings.JENKINS_WEBHOOK_SECRET:
    jenkins_headers["X-Jenkins-Signature"] = "sha256=" + hmac.new(
        settings.JENKINS_WEBHOOK_SECRET.encode(), jenkins_body, hashlib.sha256
    ).hexdigest()
s, d = post("/webhook/jenkins", jenkins_payload, headers=jenkins_headers)
check("POST /webhook/jenkins", s == 200, str(d.get("received", "")))

s, d = post("/ui/queue/99999/cancel")
check("POST /ui/queue/{id}/cancel 404 on missing", s == 404)

s, d = post("/ui/scheduler/mode", {"mode": "FIFO"})
check("POST /ui/scheduler/mode", s == 200, d.get("mode", ""))
post("/ui/scheduler/mode", {"mode": "Priority"})  # reset

# ── Summary ──────────────────────────────────────────────────────────────────
print()
total  = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"RESULT: {passed}/{total} passed, {failed} failed")
if failed:
    print("\nFAILURES:")
    for sym, label, detail in results:
        if sym == FAIL:
            print(f"  {FAIL} {label}  [{detail}]")
sys.exit(0 if failed == 0 else 1)
