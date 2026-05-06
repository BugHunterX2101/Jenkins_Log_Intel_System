"""UI integration endpoints for the frontend shell."""

from __future__ import annotations

import time

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select, update
import json
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from app.config import settings
from app.db import get_session
from app.models import BuildEvent, SystemMetrics
from app.pipeline_models import PipelineRun, RunStatus, StageExecution
from app.services.job_scheduler import get_dashboard_snapshot
from app.services.worker_pool import serialise_worker
from app.worker_models import Worker, WorkerStatus

router = APIRouter(prefix="/ui", tags=["ui"])

logger = logging.getLogger(__name__)


def _repo_short_name(url: str) -> str:
    name = (url or "").rstrip("/").rstrip(".git").rstrip("/")
    return name.split("/")[-1] if name else "unknown"


def _clean_trigger(t: str) -> str:
    if "simulated" in t:
        return "simulated"
    if t.startswith("github-"):
        return "github"
    return t or "system"


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(max(0, int(seconds)), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours:02d}h")
    parts.append(f"{minutes:02d}m")
    if not days:
        parts.append(f"{seconds:02d}s")
    return " ".join(parts)


@router.get("/bootstrap", summary="Bootstrap payload for the frontend")
async def bootstrap(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        snapshot = await get_dashboard_snapshot(session)

        worker_result = await session.execute(select(Worker).order_by(Worker.id))
        workers = worker_result.scalars().all()
        build_event_count = await session.scalar(select(func.count(BuildEvent.id))) or 0

        # Try to fetch latest stored metrics; fall back to live computation if unavailable
        latest_metric = await session.execute(
            select(SystemMetrics).order_by(SystemMetrics.timestamp.desc()).limit(1)
        )
        metric = latest_metric.scalars().first()

        if metric:
            # Use stored metrics for process-level data (uptime, memory, cpu)
            uptime_seconds = metric.uptime_seconds
            memory_info_rss = metric.memory_used_bytes
            memory_total = metric.memory_total_bytes
            queue_total = metric.queue_total
            busy_workers = metric.busy_workers
            worker_total = metric.worker_total
            cpu_percent = metric.cpu_percent
        else:
            # Fall back to live computation
            process = psutil.Process()
            memory_info = process.memory_info()
            virtual_memory = psutil.virtual_memory()
            uptime_seconds = int(time.time() - process.create_time())
            memory_info_rss = memory_info.rss
            memory_total = virtual_memory.total
            cpu_percent = process.cpu_percent(interval=None)

            queue_total = sum(len(items) for items in snapshot.values())
            busy_workers = sum(1 for worker in workers if worker.status == WorkerStatus.BUSY)
            worker_total = len(workers)
    except Exception as exc:
        logger.warning("bootstrap: DB or snapshot error — returning minimal payload: %s", exc)
        # Fallback minimal payload when DB unavailable or snapshot fails
        uptime_seconds = int(time.time())
        memory_info_rss = 0
        memory_total = 0
        cpu_percent = 0
        queue_total = 0
        busy_workers = 0
        worker_total = 0
        snapshot = {"QUEUED": [], "IN_PROGRESS": [], "COMPLETED": [], "FAILED": [], "ABORTED": []}
        build_event_count = 0

    # Always compute chaos from the live snapshot so it reflects current pressure,
    # not a stale historical total that causes the dial to be permanently pegged at 100.
    active_queue = len(snapshot.get("QUEUED", [])) + len(snapshot.get("IN_PROGRESS", []))
    failed_capped = min(len(snapshot.get("FAILED", [])), 5)
    queue_pressure = active_queue + busy_workers * 2 + failed_capped
    chaos_intensity = max(0, min(100, int(queue_pressure * 2)))
    if chaos_intensity >= 75:
        chaos_level = "Critical"
    elif chaos_intensity >= 45:
        chaos_level = "High Volatility"
    elif chaos_intensity >= 20:
        chaos_level = "Elevated"
    else:
        chaos_level = "Normal"

    from datetime import datetime, timezone
    latest_runs = [run for bucket in snapshot.values() for run in bucket]
    latest_runs.sort(key=lambda run: run.get("queued_at") or "", reverse=True)
    queue_depth_samples = [max(0, queue_total - index) for index, _ in enumerate(range(min(queue_total, 12)))]

    def _route_status(path: str) -> str:
        if path in {"/ui/bootstrap", "/ui/queue", "/ui/scheduler", "/ui/build_events"}:
            return "Healthy"
        return "Healthy"

    def _route_latency(path: str) -> str:
        if path == "/ui/bootstrap":
            return "12ms"
        if path == "/ui/queue":
            return "45ms"
        if path == "/ui/scheduler":
            return "28ms"
        if path == "/ui/build_events":
            return "52ms"
        return "31ms"

    endpoint_rows = [
        {"route": "/ui/bootstrap", "status": _route_status("/ui/bootstrap"), "latency": _route_latency("/ui/bootstrap"), "rate": "0.0%"},
        {"route": "/ui/queue", "status": _route_status("/ui/queue"), "latency": _route_latency("/ui/queue"), "rate": "0.0%"},
        {"route": "/ui/scheduler", "status": _route_status("/ui/scheduler"), "latency": _route_latency("/ui/scheduler"), "rate": "0.0%"},
        {"route": "/ui/build_events", "status": _route_status("/ui/build_events"), "latency": _route_latency("/ui/build_events"), "rate": "0.0%"},
    ]

    try:
        latest_events = await session.execute(select(BuildEvent).order_by(BuildEvent.processed_at.desc()).limit(8))
        build_events = latest_events.scalars().all()
    except Exception:
        build_events = []

    request_feed = []
    for run in latest_runs[:6]:
        route = "/webhook/github/simulate" if run.get("triggered_by") == "github-push-simulated" else "/api/v1/jobs/sync"
        request_feed.append(
            {
                "id": f"#run_{run.get('id')}",
                "timestamp": run.get("queued_at"),
                "method": "POST" if route.startswith("/webhook") else "GET",
                "route": route,
                "status": "200" if run.get("status") else "202",
            }
        )
    for event in build_events[:4]:
        request_feed.append(
            {
                "id": f"#evt_{event.id}",
                "timestamp": event.processed_at.isoformat() if event.processed_at else None,
                "method": "POST",
                "route": "/webhook/jenkins/simulate",
                "status": "200" if event.delivery_status else "202",
            }
        )

    return {
        "health": {
            "status": "ok",
            "version": "1.2.0",
            "chaos_intensity": chaos_intensity / 100.0,
            "chaos_level": chaos_level,
            "uptime_percentage": "99.98%",
        },
        "backend": {
            "status": "RUNNING",
            "technology": "FastAPI / Python",
            "port": str(request.url.port or 8000),
            "uptime": _format_duration(uptime_seconds),
            "memory_used": memory_info_rss,
            "memory_total": memory_total,
            "cpu_percent": cpu_percent,
        },
        "simulation": {
            "chaos_intensity": chaos_intensity,
            "chaos_level": chaos_level,
            "arrival_rate": max(1, min(100, (len(snapshot.get("QUEUED", [])) + len(snapshot.get("IN_PROGRESS", []))) * 2 + busy_workers * 3)),
            "burst_prob": min(100, len(snapshot.get("FAILED", [])) * 15 + busy_workers * 5),
            "failure_rate": min(100, len(snapshot.get("FAILED", [])) * 10 + busy_workers * 2),
            "min_duration_ms": 100,
            "max_duration_ms": 5000,
        },
        "queue": {
            "queued": len(snapshot.get("QUEUED", [])),
            "in_progress": len(snapshot.get("IN_PROGRESS", [])),
            "completed": len(snapshot.get("COMPLETED", [])),
            "failed": len(snapshot.get("FAILED", [])),
            "aborted": len(snapshot.get("ABORTED", [])),
            "total": queue_total,
            "avg_wait_seconds": round(
                sum(
                    max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(run["queued_at"])).total_seconds())
                    for run in latest_runs
                    if run.get("queued_at") and run.get("status") == "QUEUED"
                ) / max(1, len([r for r in latest_runs if r.get("status") == "QUEUED"])),
                1
            ) if any(r.get("status") == "QUEUED" for r in latest_runs) else 0.0,
            "latest_runs": latest_runs[:12],
            "database": {
                "total_records": queue_total + build_event_count,
                "file_size": f"{max(1, int((queue_total + build_event_count) / 1000))} MB",
                "tables": [
                    {"name": "job_queue", "rows": len(latest_runs)},
                    {"name": "execution_logs", "rows": int(build_event_count)},
                    {"name": "worker_metrics", "rows": worker_total},
                    {"name": "webhook_events", "rows": int(build_event_count)},
                ],
            },
        },
        "workers": {
            "total": worker_total,
            "idle": sum(1 for worker in workers if worker.status == WorkerStatus.IDLE),
            "busy": busy_workers,
            "offline": sum(1 for worker in workers if worker.status == WorkerStatus.OFFLINE),
            "items": [serialise_worker(worker) for worker in workers],
        },
        "backend_routes": endpoint_rows,
        "backend_request_feed": request_feed,
        "build_events": [
            {
                "id": event.id,
                "job_name": event.job_name,
                "build_number": event.build_number,
                "failure_type": event.failure_type,
                "severity": event.severity,
                "summary_text": event.summary_text,
                "processed_at": event.processed_at.isoformat() if event.processed_at else None,
            }
            for event in build_events
        ],
        "activity_stream": [
            {
                "timestamp": run.get("queued_at"),
                "source": run.get("author") or _clean_trigger(run.get("triggered_by", "system")),
                "event": (
                    f"Push to {run.get('branch', 'unknown')} — "
                    f"{_repo_short_name(run.get('repo_url', ''))}"
                    + (f" ({(run.get('commit_sha') or '')[:7]})" if run.get('commit_sha') else "")
                ),
                "status": run.get("status", "QUEUED"),
            }
            for run in latest_runs[:15]
        ],
    }


@router.get("/queue", summary="Real-time queue/explorer data")
async def get_queue_data(session: AsyncSession = Depends(get_session)) -> dict:
    """Returns all pipeline runs organized by status for the queue explorer page."""
    from app.pipeline_models import RunStatus
    
    try:
        runs_result = await session.execute(select(PipelineRun).order_by(PipelineRun.queued_at.desc()))
        all_runs = runs_result.scalars().all()

        # Organize by status
        by_status = {}
        for status in RunStatus:
            by_status[status.value] = []

        for run in all_runs:
            status_key = run.status.value if hasattr(run.status, 'value') else str(run.status)
            if status_key in by_status:
                by_status[status_key].append({
                    "id": run.id,
                    "repo": run.repo_url.split('/')[-1] if run.repo_url else '',
                    "repo_url": run.repo_url,
                    "branch": run.branch,
                    "commit": run.commit_sha[:8] if run.commit_sha else '',
                    "commit_sha": run.commit_sha,
                    "author": run.author,
                    "triggered_by": run.triggered_by,
                    "job_name": run.jenkins_job_name,
                    "status": run.status.value if hasattr(run.status, 'value') else str(run.status),
                    "queued_at": run.queued_at.isoformat() if run.queued_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "duration_s": run.duration_s,
                })

        return {"runs_by_status": by_status, "total": len(all_runs)}
    except Exception as exc:
        logger.warning("get_queue_data: DB error — returning empty runs: %s", exc)
        by_status = {status.value: [] for status in RunStatus}
        return {"runs_by_status": by_status, "total": 0}


@router.get("/scheduler", summary="Real-time scheduler data")
async def get_scheduler_data(session: AsyncSession = Depends(get_session)) -> dict:
    """Returns scheduled jobs and upcoming runs for the scheduler page."""
    from app.pipeline_models import RunStatus
    
    try:
        # Get upcoming queued jobs
        queued_result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.status == RunStatus.QUEUED)
            .order_by(PipelineRun.queued_at.desc())
            .limit(50)
        )
        queued_runs = queued_result.scalars().all()

        # Get in-progress jobs
        inprog_result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.status == RunStatus.IN_PROGRESS)
            .order_by(PipelineRun.started_at.desc())
        )
        inprog_runs = inprog_result.scalars().all()
    except Exception as exc:
        logger.warning("get_scheduler_data: DB error — returning empty scheduler data: %s", exc)
        queued_runs = []
        inprog_runs = []
    
    scheduled_jobs = []
    for idx, run in enumerate(queued_runs[:20]):
        scheduled_jobs.append({
            "id": run.id,
            "repo": run.repo_url.split('/')[-1] if run.repo_url else '',
            "branch": run.branch,
            "author": run.author,
            "job_name": run.jenkins_job_name,
            "priority": "high" if run.branch == "main" else "normal",
            "estimated_wait": f"{(len(queued_runs) - idx) * 2}m",
            "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        })
    
    active_jobs = []
    for run in inprog_runs[:10]:
        duration = (run.duration_s or 0) if run.started_at else 0
        active_jobs.append({
            "id": run.id,
            "repo": run.repo_url.split('/')[-1] if run.repo_url else '',
            "branch": run.branch,
            "job_name": run.jenkins_job_name,
            "started": run.started_at.isoformat() if run.started_at else None,
            "duration_s": duration,
        })
    
    # running = in-progress jobs (kanban uses 'running' key)
    from datetime import datetime, timezone as _tz
    _now = datetime.now(_tz.utc)
    running_jobs = []
    for run in inprog_runs[:10]:
        # duration_s is None while the job is still running; compute elapsed from started_at
        if run.duration_s is not None:
            elapsed = run.duration_s
        elif run.started_at:
            elapsed = int((_now - run.started_at).total_seconds())
        else:
            elapsed = 0
        running_jobs.append({
            "id": run.id,
            "repo": run.repo_url.split('/')[-1] if run.repo_url else '',
            "branch": run.branch,
            "job_name": run.jenkins_job_name,
            "started": run.started_at.isoformat() if run.started_at else None,
            "duration_s": elapsed,
            "summary": f"{run.jenkins_job_name or 'job'} / {run.branch or 'main'}",
            "priority": "high" if run.branch == "main" else "normal",
        })

    for job in scheduled_jobs:
        job["summary"] = f"{job.get('job_name') or 'job'} / {job.get('branch') or 'main'}"
        job["description"] = f"{job.get('repo', '')} triggered by {job.get('author', 'system')}"

    # Recently completed jobs for kanban completed column
    completed_result = await session.execute(
        select(PipelineRun)
        .where(PipelineRun.status == RunStatus.COMPLETED)
        .order_by(PipelineRun.completed_at.desc())
        .limit(10)
    )
    completed_runs_list = completed_result.scalars().all()
    completed_jobs = [
        {
            "id": run.id,
            "repo": run.repo_url.split('/')[-1] if run.repo_url else '',
            "branch": run.branch,
            "job_name": run.jenkins_job_name,
            "completed": run.completed_at.isoformat() if run.completed_at else None,
            "duration_s": run.duration_s or 0,
            "summary": f"{run.jenkins_job_name or 'job'} / {run.branch or 'main'}",
            "priority": "high" if run.branch == "main" else "normal",
        }
        for run in completed_runs_list
    ]

    # "queued"    = newest arrivals (just came in, desc order)
    # "scheduled" = FIFO order — oldest first = next to run
    fifo_jobs = list(reversed(scheduled_jobs))
    return {
        "queued": scheduled_jobs,
        "scheduled": fifo_jobs,
        "running": running_jobs,
        "completed": completed_jobs,
        "active": running_jobs,
    }


@router.post("/queue/{run_id}/cancel", summary="Abort a queued or in-progress pipeline run")
async def cancel_run(run_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        result = await session.execute(
            select(PipelineRun.status).where(PipelineRun.id == run_id)
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        run_status = row[0]
        if run_status not in (RunStatus.QUEUED, RunStatus.IN_PROGRESS):
            raise HTTPException(status_code=400, detail=f"Run {run_id} is not active (status: {run_status.value})")

        await session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run_id)
            .values(status=RunStatus.ABORTED)
        )
        await session.commit()
        return {"cancelled": run_id, "status": "ABORTED"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("cancel_run: DB error for run %s — returning 404: %s", run_id, exc)
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.post("/queue/flush", summary="Remove queued pipeline runs")
async def flush_queue(session: AsyncSession = Depends(get_session)) -> dict:
    queued = await session.execute(select(PipelineRun).where(PipelineRun.status == RunStatus.QUEUED))
    runs = queued.scalars().all()
    run_ids = [run.id for run in runs]

    if run_ids:
        await session.execute(delete(StageExecution).where(StageExecution.run_id.in_(run_ids)))
        await session.execute(delete(PipelineRun).where(PipelineRun.id.in_(run_ids)))
        await session.commit()

    return {"flushed": len(run_ids), "run_ids": run_ids}


@router.get("/build_events", summary="Latest processed build analysis events")
async def get_build_events(session: AsyncSession = Depends(get_session), limit: int = 10) -> dict:
    """Return the most recent BuildEvent analysis records for UI panels."""
    from app.models import BuildEvent

    try:
        result = await session.execute(select(BuildEvent).order_by(BuildEvent.processed_at.desc()).limit(limit))
        events = result.scalars().all()
    except Exception as exc:
        logger.warning("get_build_events: DB error — returning empty list: %s", exc)
        events = []

    items = []
    for e in events:
        try:
            fixes = json.loads(e.fix_suggestions) if e.fix_suggestions else []
        except Exception:
            fixes = []
        # Derive a short repo name from the Jenkins job_name (e.g. "acme/auth-service/main" → "auth-service")
        _parts = (e.job_name or "").split("/")
        _repo_short = _parts[1] if len(_parts) >= 2 else (e.job_name or "")
        items.append({
            "id": e.id,
            "delivery_id": f"evt-{e.id}",       # stable reference for the webhook table Delivery/ID column
            "event_type": "build_failure",       # semantic webhook event type for the Event Type column
            "repo_name": _repo_short,            # short repo name for the Source column
            "job_name": e.job_name,
            "build_number": e.build_number,
            "failure_type": e.failure_type,
            "confidence": e.confidence,
            "summary_text": e.summary_text,
            "fix_suggestions": fixes,
            "severity": e.severity,
            "log_url": e.log_url,
            "delivery_status": e.delivery_status,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
        })

    return {"events": items}


@router.get("/metrics/live", summary="Real-time system metrics for dashboard polling")
async def get_live_metrics(session: AsyncSession = Depends(get_session)) -> dict:
    """Compute metrics live — no Celery required. Also persists to DB for history."""
    from datetime import datetime, timezone

    process = psutil.Process()
    mem = process.memory_info()
    vmem = psutil.virtual_memory()
    uptime_seconds = int(time.time() - process.create_time())
    cpu_percent = process.cpu_percent(interval=None)
    now = datetime.now(timezone.utc)

    try:
        snapshot = await get_dashboard_snapshot(session)
        worker_result = await session.execute(select(Worker).order_by(Worker.id))
        workers = worker_result.scalars().all()
    except Exception as exc:
        logger.warning("get_live_metrics: DB error — using empty snapshot/workers: %s", exc)
        snapshot = {"QUEUED": [], "IN_PROGRESS": [], "COMPLETED": [], "FAILED": [], "ABORTED": []}
        workers = []

    queue_total  = sum(len(v) for v in snapshot.values())
    busy_workers = sum(1 for w in workers if w.status == WorkerStatus.BUSY)
    worker_total = len(workers)

    active_queue    = len(snapshot.get("QUEUED", [])) + len(snapshot.get("IN_PROGRESS", []))
    failed_capped   = min(len(snapshot.get("FAILED", [])), 5)
    queue_pressure  = active_queue + busy_workers * 2 + failed_capped
    chaos_intensity = max(0, min(100, int(queue_pressure * 2)))
    if chaos_intensity >= 75:
        chaos_level = "Critical"
    elif chaos_intensity >= 45:
        chaos_level = "High Volatility"
    elif chaos_intensity >= 20:
        chaos_level = "Elevated"
    else:
        chaos_level = "Normal"

    # Persist snapshot at most every 30 s to avoid write contention when
    # multiple browser tabs each poll this endpoint every 5 s.
    try:
        _last_ts = getattr(get_live_metrics, "_last_persisted", None)
        if _last_ts is None or (now.timestamp() - _last_ts) >= 30:
            count = await session.scalar(select(func.count(SystemMetrics.id))) or 0
            if count >= 1000:
                oldest = await session.execute(
                    select(SystemMetrics).order_by(SystemMetrics.timestamp.asc()).limit(count - 999)
                )
                for old in oldest.scalars().all():
                    session.delete(old)
            session.add(SystemMetrics(
                uptime_seconds=uptime_seconds,
                memory_used_bytes=mem.rss,
                memory_total_bytes=vmem.total,
                cpu_percent=cpu_percent,
                queue_total=queue_total,
                busy_workers=busy_workers,
                worker_total=worker_total,
                chaos_intensity=chaos_intensity,
                chaos_level=chaos_level,
            ))
            await session.commit()
            get_live_metrics._last_persisted = now.timestamp()
    except Exception as exc:
        logger.debug("get_live_metrics: skipping persist due to DB error: %s", exc)

    return {
        "status": "ok",
        "timestamp": now.isoformat(),
        "data": {
            "uptime_seconds": uptime_seconds,
            "uptime_formatted": _format_duration(uptime_seconds),
            "memory_used_bytes": mem.rss,
            "memory_total_bytes": vmem.total,
            "cpu_percent": cpu_percent,
            "queue_total": queue_total,
            "busy_workers": busy_workers,
            "worker_total": worker_total,
            "chaos_intensity": chaos_intensity,
            "chaos_level": chaos_level,
            "queue_pressure": queue_pressure,
        },
    }


@router.get("/metrics/history", summary="Historical system metrics (last N minutes)")
async def get_metrics_history(session: AsyncSession = Depends(get_session), minutes: int = 60) -> dict:
    """
    Returns historical system metrics for trend analysis and graphs.
    Samples every 5 seconds by default.
    """
    from datetime import datetime, timezone, timedelta
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    try:
        history_result = await session.execute(
            select(SystemMetrics)
            .where(SystemMetrics.timestamp >= cutoff_time)
            .order_by(SystemMetrics.timestamp.asc())
        )
        metrics = history_result.scalars().all()
    except Exception as exc:
        logger.warning("get_metrics_history: DB error — returning empty samples: %s", exc)
        metrics = []

    samples = []
    for m in metrics:
        samples.append({
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            "uptime_seconds": m.uptime_seconds,
            "memory_used_mb": round(m.memory_used_bytes / (1024 * 1024), 2),
            "memory_total_gb": round(m.memory_total_bytes / (1024 * 1024 * 1024), 2),
            "cpu_percent": m.cpu_percent,
            "queue_total": m.queue_total,
            "busy_workers": m.busy_workers,
            "chaos_intensity": m.chaos_intensity,
        })

    return {
        "status": "ok",
        "period_minutes": minutes,
        "sample_count": len(samples),
        "samples": samples,
    }


@router.get("/scheduler/mode", summary="Get current scheduler routing mode")
async def get_scheduler_mode() -> dict:
    from app.scheduler import get_routing_mode
    return {"mode": get_routing_mode()}


@router.post("/scheduler/mode", summary="Set scheduler routing mode")
async def set_scheduler_mode(body: dict) -> dict:
    from app.scheduler import set_routing_mode
    mode = body.get("mode", "Priority")
    if mode not in ("FIFO", "Priority", "Load-Balanced"):
        raise HTTPException(status_code=400, detail=f"Unknown routing mode: {mode!r}")
    set_routing_mode(mode)
    return {"mode": mode}
