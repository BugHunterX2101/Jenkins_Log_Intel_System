# COMPREHENSIVE ERROR CATALOG
## Jenkins Log Intelligence System - Full Audit

**Audit Date**: May 5, 2026  
**Test Results**: 51-52/62 passing (variable due to connection pool exhaustion)  
**Critical Issues Found**: 1 (Multiple database engines)  
**High Priority Issues**: 0  
**Medium Priority Issues**: 1 (Intermittent chaos test)  
**Low Priority Issues**: 0  

---

## ERROR #1: CRITICAL - Multiple Database Engine Instances

### Location
- `app/routers/jobs.py` line 29
- `app/routers/ui.py` line 28  
- `app/routers/workers.py` line 19
- `app/routers/github_webhook.py` line 97

### Current Behavior
Each router independently calls:
```python
engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

### Problem
- **4 separate AsyncEngine instances** are created, each with its own connection pool
- Under load (46 sequential API calls), connections get exhausted
- After webhook POST endpoints (which consume DB connections for writes), **subsequent requests timeout**
- Tests pass initially but fail around call 35-40 when pool exhausted
- This causes cascading failures in dependent endpoint tests

### Affected Endpoints (Fail with connection timeout)
- `POST /webhook/jenkins/simulate` → Timeout
- `POST /ui/queue/99999/cancel` → Timeout  
- `GET /jobs` → HTTP 0 (connection error)
- `GET /jobs/dashboard` → HTTP 0
- `GET /jobs/1` → HTTP 0
- `GET /ui/metrics/history` → Timeout
- `GET /health` → Timeout

### Root Cause
Per SQLAlchemy async best practices, a **single engine should be shared** application-wide.  Multiple engines create redundant connection pools that exhaust resources.

### Expected Fix
Move engine creation to `main.py` app startup, inject sessions via FastAPI dependency injection.

### Severity
**CRITICAL** - Causes complete service degradation under moderate load

### Test Evidence
```
RESULT: 51/62 passed, 11 failed

Passing pattern:
✅ BOOTSTRAP - 12 pass (pool fresh)
✅ QUEUE - 6 pass
✅ SCHEDULER - 7 pass  
✅ BUILD_EVENTS - 7 pass
✅ LIVE_METRICS - 4/5 pass (1 intermittent)
✅ WORKERS - 6 pass
✅ SCHEDULER_MODE - 3 pass

Then: After POST endpoints (~call 35-40)...

❌ Subsequent requests: FAIL (connection timeout)
❌ GET /jobs - timeout
❌ GET /jobs/1 - HTTP 0
❌ GET /health - timeout  
```

---

## ERROR #2: MEDIUM - Intermittent chaos_intensity Test Failure

### Location
`func_test.py` line 106  
`app/routers/ui.py` (live metrics endpoint)

### Current Behavior
Test: `chk("chaos_intensity < 100", ...)`

Test expects: `chaos_intensity < 100`  
Actual value sometimes: `chaos_intensity = 100`

### Problem
Simulation generates chaos_intensity as `random.randint(0, 100)` which includes 100.  
Test checks for strictly `< 100`, so 100 is considered a failure.

### Affected Test
- ✅ "LIVE METRICS" section, check: "chaos_intensity < 100"

### Root Cause
Test constraint is too strict; simulator can legitimately generate 100.

### Expected Fix
Either:  
1. Change test to `<= 100`, OR
2. Change simulator to generate `randint(0, 99)`

### Severity
**MEDIUM** - Intermittent (~1-2 failures per test run), non-blocking

### Test Evidence
```
=== LIVE METRICS (/ui/metrics/live) ===
  PASS  HTTP 200
  FAIL  chaos_intensity < 100  [100]    ← Fails when value is 100
  PASS  uptime_formatted present  [08m 13s]
  ...
```

---

## SUMMARY TABLE

| Error ID | Type | Severity | Component | Status | Impact |
|----------|------|----------|-----------|--------|--------|
| #1 | Architecture | CRITICAL | DB Connection Pool | Found | 9-10 test failures, service degradation |
| #2 | Logic | MEDIUM | Chaos Simulator | Found | 1-2 intermittent test failures |

---

## VALIDATION NOTES

### Endpoints Verified Working (via direct probes)
- ✅ `POST /webhook/jenkins/simulate` - Returns correct structure when tested individually
- ✅ `POST /ui/queue/99999/cancel` - Returns 404 correctly
- ✅ `GET /jobs` - Returns 5 status buckets
- ✅ `GET /jobs/dashboard` - Returns 5 status buckets
- ✅ `GET /ui/metrics/history` - Returns status="ok" and samples list
- ✅ `GET /health` - Returns 200 with status="ok"

**Conclusion**: Endpoint code is correct; failures are infrastructure-related (connection pool exhaustion).

### Code Quality Observations
✅ All endpoints have proper error handling (DB errors map to 404)  
✅ Async/await patterns appear correct  
✅ Request validation with Pydantic models  
✅ Proper HTTPException usage  

### Failure Pattern Analysis
```
Time →

Stage 1: ✅ Early tests pass
  - Calls 1-30: All return < 100ms, connections available

Stage 2: 🔄 Resource contention begins  
  - Calls 31-35: Slight delays, some connections in use
  
Stage 3: ❌ Pool exhaustion
  - Calls 36+: Timeouts, HTTP 0, connection refused
  - GET /jobs returns after 10s timeout with no response
  - GET /health unreachable
```

---

## NEXT STEPS

1. **Fix Error #1** (CRITICAL):
   - Consolidate all 4 engine instances into single shared engine in `main.py`
   - Update all routers to receive SessionFactory via dependency injection
   - Test with connection pool size limits

2. **Fix Error #2** (MEDIUM):
   - Update test constraint or simulator configuration
   - Validate with 10+ test runs

3. **Validation**:
   - Run func_test.py - expect 62/62 passing
   - Run individual endpoint probes
   - Check server logs for connection pool warnings

---

## FILE MANIFEST (Files to Modify)

| File | Changes Required | Severity |
|------|------------------|----------|
| `main.py` | Create single AsyncEngine, share via app context | CRITICAL |
| `app/routers/jobs.py` | Remove `create_async_engine`, use injected SessionFactory | CRITICAL |
| `app/routers/ui.py` | Remove `create_async_engine`, use injected SessionFactory | CRITICAL |
| `app/routers/workers.py` | Remove `create_async_engine`, use injected SessionFactory | CRITICAL |
| `app/routers/github_webhook.py` | Remove `create_async_engine`, use injected SessionFactory | CRITICAL |
| `func_test.py` | Adjust chaos_intensity test constraint OR simulator | MEDIUM |
