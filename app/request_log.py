"""
In-memory HTTP request log — captures real latency and status for every API call.
Used to power the Live Request Feed and Endpoint Health Monitor on the Backend Console.
"""
from __future__ import annotations

from collections import deque, defaultdict
from datetime import datetime, timezone

_request_log: deque = deque(maxlen=100)
_route_latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
_route_errors: dict[str, list] = defaultdict(lambda: deque(maxlen=50))
_counter = 0


def log_request(method: str, path: str, status: int, latency_ms: float) -> None:
    global _counter
    _counter += 1
    _request_log.appendleft({
        "id": f"#{_counter:04d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "route": path,
        "status": str(status),
        "latency_ms": round(latency_ms, 1),
    })
    _route_latencies[path].appendleft(latency_ms)
    _route_errors[path].appendleft(1 if status >= 400 else 0)


def get_recent(n: int = 20) -> list:
    return list(_request_log)[:n]


def get_route_stats(path: str) -> dict:
    lats = list(_route_latencies.get(path) or [])
    errs = list(_route_errors.get(path) or [])
    avg_lat = f"{sum(lats) / len(lats):.0f}ms" if lats else "-"
    err_rate = f"{(sum(errs) / len(errs) * 100):.1f}%" if errs else "-"
    return {"latency": avg_lat, "rate": err_rate}
