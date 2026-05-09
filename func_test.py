"""Full functional test of every API endpoint the frontend uses."""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            body = r.read()
            try: return r.status, json.loads(body)
            except: return r.status, {}
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {}
    except Exception as ex:
        return 0, {"error": str(ex)}

def post(path, data=None, headers=None):
    body = json.dumps(data or {}).encode()
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(BASE + path, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
            try: return r.status, json.loads(body)
            except: return r.status, {}
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {}
    except Exception as ex:
        return 0, {"error": str(ex)}

results = []
def chk(label, ok, info=""):
    sym = "PASS" if ok else "FAIL"
    results.append((sym, label, info))
    print(f"  {sym}  {label}" + (f"  [{info}]" if info else ""))

# ── Bootstrap ────────────────────────────────────────────────────────────
print("\n=== BOOTSTRAP (/ui/bootstrap) ===")
s, d = get("/ui/bootstrap")
chk("HTTP 200", s == 200)
q   = d.get("queue", {})
sim = d.get("simulation", {})
h   = d.get("health", {})
be  = d.get("backend", {})
w   = d.get("workers", {})
chk("queue.queued present",           "queued" in q, str(q.get("queued")))
chk("queue.in_progress present",      "in_progress" in q, str(q.get("in_progress")))
chk("queue.database.tables list",     isinstance(q.get("database", {}).get("tables"), list))
chk("simulation.arrival_rate <= 100", sim.get("arrival_rate", 999) <= 100, str(sim.get("arrival_rate")))
chk("health.chaos_intensity 0-1",     0 <= h.get("chaos_intensity", -1) <= 1.0, str(round(h.get("chaos_intensity", 0)*100)) + "%")
chk("backend.memory_used int",        isinstance(be.get("memory_used"), int))
chk("backend.uptime present",         bool(be.get("uptime")), be.get("uptime", ""))
chk("workers.items is list",          isinstance(w.get("items"), list), str(len(w.get("items", []))))
chk("activity_stream is list",        isinstance(d.get("activity_stream"), list))
chk("build_events is list",           isinstance(d.get("build_events"), list))
chk("backend_routes is list",         isinstance(d.get("backend_routes"), list))

# ── Queue ────────────────────────────────────────────────────────────────
print("\n=== QUEUE (/ui/queue) ===")
s, d = get("/ui/queue")
chk("HTTP 200", s == 200)
rbs = d.get("runs_by_status", {})
chk("5 status buckets", set(rbs.keys()) == {"QUEUED","IN_PROGRESS","COMPLETED","FAILED","ABORTED"})
sample = next((r for v in rbs.values() for r in v), None)
if sample:
    needed = ["id", "repo", "branch", "status", "queued_at"]
    chk("run has required fields", all(k in sample for k in needed))
    chk("run.commit present",  "commit" in sample, str(sample.get("commit", "")))
    chk("run.author present",  "author" in sample)
    chk("run.duration_s present", "duration_s" in sample)

# ── Scheduler ────────────────────────────────────────────────────────────
print("\n=== SCHEDULER (/ui/scheduler) ===")
s, d = get("/ui/scheduler")
chk("HTTP 200", s == 200)
chk("has queued key",    "queued" in d, str(len(d.get("queued", []))))
chk("has scheduled key", "scheduled" in d, str(len(d.get("scheduled", []))))
chk("has running key",   "running" in d, str(len(d.get("running", []))))
chk("has completed key", "completed" in d, str(len(d.get("completed", []))))
running = d.get("running", [])
if running:
    r = running[0]
    chk("running item has id/repo/branch/job_name", all(k in r for k in ["id","repo","branch","job_name"]))
    chk("running item has started/duration_s/priority", all(k in r for k in ["started","duration_s","priority"]))
    chk("running item has summary", "summary" in r, r.get("summary", "")[:30])

# ── Build events ─────────────────────────────────────────────────────────
print("\n=== BUILD EVENTS (/ui/build_events) ===")
s, d = get("/ui/build_events")
chk("HTTP 200", s == 200)
evts = d.get("events", [])
chk("events list non-empty", len(evts) > 0, str(len(evts)))
if evts:
    e = evts[0]
    chk("event_type present",      "event_type" in e, e.get("event_type", ""))
    chk("repo_name present",       "repo_name" in e, e.get("repo_name", ""))
    chk("delivery_id present",     "delivery_id" in e, str(e.get("delivery_id", "")))
    chk("delivery_status != PENDING", e.get("delivery_status") != "PENDING", e.get("delivery_status", ""))
    chk("fix_suggestions list",    isinstance(e.get("fix_suggestions"), list))
    chk("summary_text non-empty",  bool(e.get("summary_text")))

# ── Live metrics ─────────────────────────────────────────────────────────
print("\n=== LIVE METRICS (/ui/metrics/live) ===")
s, d = get("/ui/metrics/live")
chk("HTTP 200", s == 200)
data = d.get("data", {})
chk("chaos_intensity < 100",    data.get("chaos_intensity", 100) < 100, str(data.get("chaos_intensity")))
chk("uptime_formatted present", bool(data.get("uptime_formatted")), data.get("uptime_formatted", ""))
chk("memory_used_bytes int",    isinstance(data.get("memory_used_bytes"), int))
chk("cpu_percent present",      "cpu_percent" in data)
chk("queue_pressure < queue_total",
    data.get("queue_pressure", 9999) < data.get("queue_total", 0),
    f"pressure={data.get('queue_pressure')} total={data.get('queue_total')}")

# ── Workers ──────────────────────────────────────────────────────────────
print("\n=== WORKERS (/api/workers) ===")
s, d = get("/api/workers")
chk("HTTP 200", s == 200)
ws = d.get("workers", [])
chk("workers non-empty", len(ws) > 0, str(len(ws)))
if ws:
    w = ws[0]
    chk("has id/name/status/load",  all(k in w for k in ["id","name","status","load"]))
    chk("has capabilities",         "capabilities" in w, str(w.get("capabilities", ""))[:30])
    chk("has jobs_run/current_job", all(k in w for k in ["jobs_run","current_job"]))
summary = d.get("summary", {})
chk("summary has total/idle/busy", all(k in summary for k in ["total","idle","busy"]))

# ── Scheduler mode ────────────────────────────────────────────────────────
print("\n=== SCHEDULER MODE ===")
s, d = get("/ui/scheduler/mode")
chk("GET mode 200", s == 200, d.get("mode", ""))
s, d = post("/ui/scheduler/mode", {"mode": "FIFO"})
chk("POST mode FIFO 200", s == 200, d.get("mode", ""))
s, d = post("/ui/scheduler/mode", {"mode": "Priority"})
chk("POST mode Priority 200", s == 200)

# ── Write endpoints ────────────────────────────────────────────────────────
print("\n=== WRITE ENDPOINTS ===")

github_payload = {
    "ref": "refs/heads/main",
    "after": "abc123def4567890abc123def4567890abc123de",
    "repository": {
        "name": "pipeline-engine",
        "full_name": "acme/pipeline-engine",
        "clone_url": "https://github.com/acme/pipeline-engine.git",
        "html_url": "https://github.com/acme/pipeline-engine",
    },
    "pusher": {"name": "func-test"},
    "head_commit": {"id": "abc123def4567890abc123def4567890abc123de"},
}
s, d = post("/webhook/github", github_payload, headers={"X-GitHub-Event": "push"})
chk("POST /webhook/github", s == 200, str(d.get("repo", "")))
chk("  received real webhook", d.get("received") is True)

jenkins_payload = {
    "build": {
        "number": 12847,
        "phase": "FINALIZED",
        "status": "FAILURE",
        "url": "http://jenkins.example/job/backend-tests/12847/",
        "result": "FAILURE",
    }
}
s, d = post("/webhook/jenkins", jenkins_payload)
chk("POST /webhook/jenkins", s == 200, str(d.get("received", "")))

s, d = post("/ui/queue/99999/cancel")
chk("POST cancel 404 on missing", s == 404)

# ── Jobs ──────────────────────────────────────────────────────────────────
print("\n=== JOBS ===")
s, d = get("/jobs")
chk("GET /jobs 200", s == 200)
chk("5 status buckets", {"QUEUED","IN_PROGRESS","COMPLETED","FAILED","ABORTED"}.issubset(d))
s, _ = get("/jobs/dashboard")
chk("GET /jobs/dashboard alias 200", s == 200)
s, d2 = get("/jobs/1")
chk("GET /jobs/1 not 422", s in (200, 404), f"HTTP {s}")

# ── Metrics history ────────────────────────────────────────────────────────
print("\n=== METRICS HISTORY ===")
s, d = get("/ui/metrics/history?minutes=5")
chk("GET /ui/metrics/history 200", s == 200)
chk("has status ok", d.get("status") == "ok")
chk("has samples list", isinstance(d.get("samples"), list))

# ── Health ────────────────────────────────────────────────────────────────
print("\n=== HEALTH ===")
s, d = get("/health")
chk("GET /health 200", s == 200, d.get("status", ""))

# ── Summary ───────────────────────────────────────────────────────────────
print()
total  = len(results)
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"RESULT: {passed}/{total} passed, {failed} failed")
if failed:
    print("\nFAILURES:")
    for sym, label, info in results:
        if sym == "FAIL":
            print(f"  FAIL  {label}  [{info}]")
sys.exit(0 if failed == 0 else 1)
