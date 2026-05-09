import urllib.request, json, sys

BASE = 'http://localhost:8000'

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

print("Testing endpoints exactly like func_test.py does...\n")

# Test POST /webhook/jenkins
s, d = post("/webhook/jenkins", {
    "build": {
        "number": 12847,
        "phase": "FINALIZED",
        "status": "FAILURE",
        "url": "http://jenkins.example/job/backend-tests/12847/",
        "result": "FAILURE",
    }
})
print(f"POST /webhook/jenkins:")
print(f"  status={s} (test expects 200)")
print(f"  job_name={d.get('job_name')}")
print(f"  Full response keys: {list(d.keys())}")
print(f"  Test would pass: {s == 200}")

# Test POST /ui/queue/99999/cancel
s, d = post("/ui/queue/99999/cancel")
print(f"\nPOST /ui/queue/99999/cancel:")
print(f"  status={s} (test expects 404)")
print(f"  Test would pass: {s == 404}")

# Test GET /jobs
s, d = get("/jobs")
print(f"\nGET /jobs:")
print(f"  status={s} (test expects 200)")
print(f"  Top-level keys: {list(d.keys())[:10]}")
expected_buckets = {"QUEUED","IN_PROGRESS","COMPLETED","FAILED","ABORTED"}
has_all_buckets = expected_buckets.issubset(d)
print(f"  Has all 5 buckets: {has_all_buckets}")
print(f"  Test would pass: {s == 200 and has_all_buckets}")

# Test GET /jobs/dashboard
s, d = get("/jobs/dashboard")
print(f"\nGET /jobs/dashboard:")
print(f"  status={s} (test expects 200)")
print(f"  Test would pass: {s == 200}")

# Test GET /jobs/1
s, d = get("/jobs/1")
print(f"\nGET /jobs/1:")
print(f"  status={s} (test expects 200 or 404, not 422)")
print(f"  Test would pass: {s in (200, 404)}")

# Test GET /ui/metrics/history
s, d = get("/ui/metrics/history?minutes=5")
print(f"\nGET /ui/metrics/history:")
print(f"  status={s} (test expects 200)")
print(f"  d.get('status')={d.get('status')} (test expects 'ok')")
print(f"  d.get('samples') type={type(d.get('samples'))} (test expects list)")
print(f"  Full response keys: {list(d.keys())}")
print(f"  Test would pass: {s == 200 and d.get('status') == 'ok' and isinstance(d.get('samples'), list)}")

# Test GET /health
s, d = get("/health")
print(f"\nGET /health:")
print(f"  status={s} (test expects 200)")
print(f"  d.get('status')={d.get('status')}")
print(f"  Test would pass: {s == 200}")
