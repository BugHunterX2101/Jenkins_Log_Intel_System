"""
Shared utility functions used across routers and services.
"""
from __future__ import annotations


def compute_chaos(snapshot: dict, busy_workers: int) -> tuple[int, str]:
    """
    Compute chaos intensity (0–100) and level from the real queue/worker state.
    Single source of truth — used by both bootstrap and metrics collection.
    """
    active_queue  = len(snapshot.get("QUEUED", [])) + len(snapshot.get("IN_PROGRESS", []))
    failed_capped = min(len(snapshot.get("FAILED", [])), 5)
    queue_pressure = active_queue + busy_workers * 2 + failed_capped
    intensity = max(0, min(100, int(queue_pressure * 2)))

    if intensity >= 75:
        level = "Critical"
    elif intensity >= 45:
        level = "High Volatility"
    elif intensity >= 20:
        level = "Elevated"
    else:
        level = "Normal"

    return intensity, level


async def check_db_health() -> bool:
    """Return True if PostgreSQL is reachable, False otherwise."""
    try:
        from app.db import get_engine
        from sqlalchemy import text
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
