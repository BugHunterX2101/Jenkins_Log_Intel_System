"""
Scheduler Loop — the Jenkins Master brain.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import psutil
from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

# ── Routing mode shared state ─────────────────────────────────────────────────
# Set via POST /ui/scheduler/mode; read by _scheduler_tick_async each tick.
_routing_mode: str = "Priority"


def get_routing_mode() -> str:
    return _routing_mode


def set_routing_mode(mode: str) -> None:
    global _routing_mode
    _routing_mode = mode


# ── SSE broadcast registry ────────────────────────────────────────────────────
# Clients subscribe by registering an asyncio.Queue; each scheduler tick
# puts a JSON-encoded SSE message into every registered queue.

_sse_clients: set[asyncio.Queue] = set()
_sse_lock = asyncio.Lock()


async def register_sse_client(q: asyncio.Queue) -> None:
    async with _sse_lock:
        _sse_clients.add(q)


async def unregister_sse_client(q: asyncio.Queue) -> None:
    async with _sse_lock:
        _sse_clients.discard(q)


async def broadcast_sse(event_type: str, data: dict) -> None:
    async with _sse_lock:
        clients = list(_sse_clients)
    if not clients:
        return
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for q in clients:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass

celery_app = Celery(
    "scheduler",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    include=["app.pipeline_tasks", "app.tasks"],
    beat_schedule={
        "scheduler-tick": {
            "task": "app.scheduler.scheduler_tick",
            "schedule": 5.0,
        },
        "collect-system-metrics": {
            "task": "app.scheduler.collect_system_metrics",
            "schedule": 5.0,
        },
    },
)


@celery_app.task(name="app.scheduler.scheduler_tick")
def scheduler_tick() -> dict:
    return asyncio.run(_scheduler_tick_async(use_celery=True))


async def _recover_stale_workers(Session) -> int:
    """
    Two-phase recovery run on every scheduler tick:

    Phase 1 — Stale BUSY workers: reset workers whose heartbeat is older than
    WORKER_HEARTBEAT_TIMEOUT_MINUTES and revert their IN_PROGRESS runs to QUEUED.

    Phase 2 — Orphaned IN_PROGRESS runs: runs that have been IN_PROGRESS for
    longer than the timeout AND have no jenkins_build_url (Jenkins never
    acknowledged them) are scheduler artefacts — revert them to QUEUED and
    release their assigned worker if it is still BUSY.

    Returns the total number of workers/runs recovered.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from app.worker_models import Worker, WorkerStatus, WorkerAssignment, AssignmentStatus
    from app.pipeline_models import PipelineRun, RunStatus

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.WORKER_HEARTBEAT_TIMEOUT_MINUTES)
    recovered = 0

    async with Session() as session:
        # ── Phase 1: stale BUSY workers ──────────────────────────────────────
        stale_result = await session.execute(
            select(Worker).where(
                Worker.status == WorkerStatus.BUSY,
                Worker.last_heartbeat < cutoff,
            )
        )
        for worker in stale_result.scalars().all():
            logger.warning(
                "Recovering stale worker %s (last_heartbeat=%s, timeout=%dm)",
                worker.name, worker.last_heartbeat, settings.WORKER_HEARTBEAT_TIMEOUT_MINUTES,
            )
            assign_result = await session.execute(
                select(WorkerAssignment).where(
                    WorkerAssignment.worker_id == worker.id,
                    WorkerAssignment.completed_at.is_(None),
                )
            )
            for assignment in assign_result.scalars().all():
                run_result = await session.execute(
                    select(PipelineRun).where(
                        PipelineRun.id == assignment.run_id,
                        PipelineRun.status == RunStatus.IN_PROGRESS,
                    )
                )
                run = run_result.scalar_one_or_none()
                if run:
                    run.status = RunStatus.QUEUED
                    run.started_at = None
                    logger.warning("Reverted run %d to QUEUED (stale worker %s)", run.id, worker.name)
                assignment.status = AssignmentStatus.FAILED
                assignment.completed_at = now
                assignment.result = "TIMEOUT"

            worker.status = WorkerStatus.IDLE
            worker.load = 0.0
            worker.current_job = None
            worker.last_heartbeat = now
            recovered += 1

        # ── Phase 2: orphaned IN_PROGRESS runs (no Jenkins build_url, timed out) ──
        # Also catches runs with started_at IS NULL (NULL < cutoff is always false in PG,
        # so we must add the IS NULL arm explicitly to recover stuck ghost runs).
        from sqlalchemy import or_
        orphan_result = await session.execute(
            select(PipelineRun).where(
                PipelineRun.status == RunStatus.IN_PROGRESS,
                PipelineRun.jenkins_build_url.is_(None),
                or_(
                    PipelineRun.started_at < cutoff,
                    PipelineRun.started_at.is_(None),
                ),
            )
        )
        for run in orphan_result.scalars().all():
            logger.warning(
                "Recovering orphaned IN_PROGRESS run %d (started_at=%s, no Jenkins build URL)",
                run.id, run.started_at,
            )
            # Release the assigned worker if still BUSY
            assign_result = await session.execute(
                select(WorkerAssignment).where(
                    WorkerAssignment.run_id == run.id,
                    WorkerAssignment.completed_at.is_(None),
                )
            )
            for assignment in assign_result.scalars().all():
                worker_result = await session.execute(
                    select(Worker).where(Worker.id == assignment.worker_id)
                )
                worker = worker_result.scalar_one_or_none()
                if worker and worker.status == WorkerStatus.BUSY:
                    worker.status = WorkerStatus.IDLE
                    worker.load = max(0.0, worker.load - 0.5)
                    worker.current_job = None
                    worker.last_heartbeat = now
                    recovered += 1
                    logger.warning("Released worker %s held by orphaned run %d", worker.name, run.id)
                assignment.status = AssignmentStatus.FAILED
                assignment.completed_at = now
                assignment.result = "TIMEOUT"

            run.status = RunStatus.QUEUED
            run.started_at = None

        await session.commit()

    return recovered


async def _scheduler_tick_async(use_celery: bool = False) -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select, update
    from app.db import get_session_factory
    from app.pipeline_models import PipelineRun, RunStatus, branch_priority_expr
    from app.services.realtime_data import real_pipeline_run_clause
    from app.services.worker_pool import assign_worker, detect_language

    # ── Hard cap on concurrent in-process execution threads ─────────────────
    # Each thread creates its own DB engine + asyncpg connection pool.
    # Without this cap, 30+ threads running concurrently exhaust PostgreSQL's
    # max_connections, making the server unresponsive.
    if not use_celery:
        active_exec = sum(
            1 for t in threading.enumerate() if t.name.startswith("exec-run-")
        )
        if active_exec >= settings.MAX_CONCURRENT_EXECUTIONS:
            logger.debug("Scheduler: %d exec threads active — skipping dispatch", active_exec)
            return {"queued_processed": 0, "assigned": 0, "skipped": True}

    engine = None
    if use_celery:
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
    else:
        Session = get_session_factory()

    await _recover_stale_workers(Session)

    assigned_count = 0

    mode = get_routing_mode()
    ordering = (
        (branch_priority_expr(), PipelineRun.queued_at.asc())
        if mode == "Priority"
        else (PipelineRun.queued_at.asc(),)
    )

    async with Session() as session:
        result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.status == RunStatus.QUEUED, real_pipeline_run_clause())
            .order_by(*ordering)
            .limit(settings.MAX_CONCURRENT_EXECUTIONS)
        )
        queued_runs = result.scalars().all()

    for run in queued_runs:
        stage_names = run.stage_names

        async with Session() as session:
            # Atomically claim the run: only the tick that flips QUEUED → IN_PROGRESS
            # proceeds; concurrent ticks see rowcount=0 and skip.
            from datetime import datetime, timezone
            claim_result = await session.execute(
                update(PipelineRun)
                .where(
                    PipelineRun.id == run.id,
                    PipelineRun.status == RunStatus.QUEUED,  # atomic guard
                )
                .values(
                    status=RunStatus.IN_PROGRESS,
                    started_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

            if claim_result.rowcount == 0:  # type: ignore[attr-defined]
                # Another tick already claimed this run — skip it
                logger.debug("Scheduler: run %d already claimed, skipping", run.id)
                continue

            language = detect_language(run.repo_url, stage_names)
            worker   = await assign_worker(session, run.id, language)

        if worker:
            if use_celery:
                execute_pipeline_run.delay(  # type: ignore[attr-defined]
                    run_id=run.id,
                    worker_id=worker.id,
                    stage_names=stage_names,
                    worker_name=worker.name,
                )
            else:
                # Running inside FastAPI process — execute in a daemon thread.
                # Use new_event_loop() instead of asyncio.run() to avoid
                # signal-handler restrictions that apply to non-main threads.
                def _exec_in_thread(rid=run.id, wid=worker.id, stages=stage_names):
                    # asyncpg requires SelectorEventLoop on Windows;
                    # ProactorEventLoop (the Windows default) causes silent hangs.
                    loop = asyncio.SelectorEventLoop()
                    asyncio.set_event_loop(loop)
                    try:
                        logger.debug("Execution thread starting run %d", rid)
                        result = loop.run_until_complete(_run_execution(rid, wid, stages))
                        logger.info("Run %d execution completed: success=%s", rid, result)
                    except Exception as _exc:
                        logger.error("Run %d execution failed: %s", rid, _exc, exc_info=True)
                    finally:
                        loop.close()
                t = threading.Thread(target=_exec_in_thread, daemon=True, name=f"exec-run-{run.id}")
                t.start()
                logger.info("Execution thread launched for run %d", run.id)
            logger.info(
                "Scheduler: dispatched run %d to worker %s (lang=%s, celery=%s)",
                run.id, worker.name, language.value, use_celery,
            )
            assigned_count += 1
        else:
            # No worker available — revert run back to QUEUED so next tick retries
            async with Session() as session:
                await session.execute(
                    update(PipelineRun)
                    .where(PipelineRun.id == run.id)
                    .values(status=RunStatus.QUEUED, started_at=None)
                )
                await session.commit()
            logger.debug("Scheduler: no idle worker for run %d — reverting to QUEUED", run.id)

    # ── Phase 6: auto-retry eligible FAILED runs ─────────────────────────────
    from datetime import timedelta as _td
    _retry_now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    backoffs = settings.PIPELINE_RETRY_BACKOFF_SECONDS

    async with Session() as session:
        retry_result = await session.execute(
            select(PipelineRun)
            .where(
                PipelineRun.status == RunStatus.FAILED,
                PipelineRun.retry_count < PipelineRun.max_retries,
                real_pipeline_run_clause(),
            )
        )
        for run in retry_result.scalars().all():
            if run.retry_after is None:
                # Newly failed — schedule the first retry after backoff delay
                delay = backoffs[min(run.retry_count, len(backoffs) - 1)]
                run.retry_after = _retry_now + _td(seconds=delay)
                logger.info(
                    "Scheduled retry for run %d (attempt %d/%d, delay=%ds)",
                    run.id, run.retry_count + 1, run.max_retries, delay,
                )
            elif (run.retry_after if run.retry_after.tzinfo else run.retry_after.replace(tzinfo=__import__('datetime').timezone.utc)) <= _retry_now:
                # Backoff elapsed — re-queue for execution
                run.retry_count += 1
                run.status = RunStatus.QUEUED
                run.started_at = None
                run.completed_at = None
                run.retry_after = None
                logger.info(
                    "Auto-retrying run %d (attempt %d/%d)",
                    run.id, run.retry_count, run.max_retries,
                )
        await session.commit()

    if engine is not None:
        await engine.dispose()
    return {"queued_processed": len(queued_runs), "assigned": assigned_count}


@celery_app.task(
    name="app.scheduler.execute_pipeline_run",
    bind=True,
    max_retries=0,
)
def execute_pipeline_run(
    self,
    run_id: int,
    worker_id: int,
    stage_names: list[str],
    worker_name: str,
) -> dict:
    logger.info(
        "Worker %s executing run %d (%d stages)",
        worker_name, run_id, len(stage_names),
    )
    success = asyncio.run(
        _run_execution(run_id, worker_id, stage_names)
    )
    return {"run_id": run_id, "worker": worker_name, "success": success}


async def _run_execution(run_id: int, worker_id: int, stage_names: list[str]) -> bool:
    """
    Execute a pipeline run against real Jenkins — no simulation fallback.

    Flow:
      1. Load run details (job_name, branch, commit_sha) from DB.
      2. Trigger the Jenkins build via the real REST API.
         If Jenkins is unreachable or returns an error → mark FAILED and return.
      3. Record the real build_number and build_url on the run.
      4. Poll Jenkins wfapi every 10 s until the build reaches a terminal status.
         _sync_stages() calls on_build_completed() internally (which releases the
         worker) when it detects SUCCESS / FAILURE / ABORTED / UNSTABLE.
      5. If 120 polling attempts (~20 min) are exhausted → mark FAILURE.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from app.pipeline_models import PipelineRun, RunStatus
    from app.services.job_scheduler import on_build_started, on_build_completed, get_run
    from app.pipeline_tasks import _trigger_jenkins, _sync_stages

    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        # 1. Fetch run details
        async with Session() as session:
            result = await session.execute(
                select(PipelineRun).where(PipelineRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if not run:
                logger.error("_run_execution: run %d not found", run_id)
                return False
            job_name   = run.jenkins_job_name
            branch     = run.branch or "main"
            commit_sha = run.commit_sha

        if not job_name:
            logger.error("_run_execution: run %d has no jenkins_job_name — cannot trigger Jenkins", run_id)
            async with Session() as session:
                await on_build_completed(session, run_id, "FAILURE")
            return False

        # 2. Trigger real Jenkins build — failure here means real failure
        try:
            build_number, build_url = await _trigger_jenkins(job_name, branch, commit_sha)
        except Exception as exc:
            logger.error(
                "_run_execution: Jenkins trigger failed for run %d (%s): %s",
                run_id, job_name, exc,
            )
            async with Session() as session:
                await on_build_completed(session, run_id, "FAILURE")
            return False

        # 3. Persist real build_number and build_url
        async with Session() as session:
            await on_build_started(session, run_id, build_number, build_url)

        logger.info(
            "_run_execution: run %d → Jenkins build #%d at %s",
            run_id, build_number, build_url,
        )

        # 4. Poll until terminal (max 120 × 10 s = 20 min)
        for attempt in range(120):
            await asyncio.sleep(10)
            try:
                done = await _sync_stages(run_id, job_name, build_number, build_url)
                if done:
                    logger.info(
                        "_run_execution: run %d completed (poll attempt %d)",
                        run_id, attempt + 1,
                    )
                    return True
            except Exception as exc:
                logger.warning(
                    "_run_execution: stage-sync error for run %d (attempt %d): %s",
                    run_id, attempt + 1, exc,
                )

        # 5. Polling exhausted — mark as FAILURE if still running
        logger.error(
            "_run_execution: run %d — poll exhausted after 120 attempts, finalising as FAILURE",
            run_id,
        )
        async with Session() as session:
            current = await get_run(session, run_id)
            if current and current.status == RunStatus.IN_PROGRESS:
                await on_build_completed(session, run_id, "FAILURE")

        return False

    finally:
        await engine.dispose()


@celery_app.task(name="app.scheduler.collect_system_metrics")
def collect_system_metrics() -> dict:
    """Periodically collect and store system metrics for real-time dashboard."""
    return asyncio.run(_collect_metrics_async())


async def _collect_metrics_async() -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select, func
    from app.models import SystemMetrics
    from app.pipeline_models import PipelineRun, RunStatus
    from app.worker_models import Worker, WorkerStatus
    from app.services.job_scheduler import get_dashboard_snapshot

    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    process = psutil.Process()
    memory_info = process.memory_info()
    virtual_memory = psutil.virtual_memory()
    uptime_seconds = int(time.time() - process.create_time())
    cpu_percent = process.cpu_percent(interval=None)

    async with Session() as session:
        snapshot = await get_dashboard_snapshot(session)

        # Get worker status
        worker_result = await session.execute(select(Worker))
        workers = worker_result.scalars().all()
        busy_workers = sum(1 for w in workers if w.status == WorkerStatus.BUSY)
        worker_total = len(workers)

        from app.utils import compute_chaos
        queue_total = sum(len(items) for items in snapshot.values())
        chaos_intensity, chaos_level = compute_chaos(snapshot, busy_workers)

        # Store metric
        metric = SystemMetrics(
            uptime_seconds=uptime_seconds,
            memory_used_bytes=memory_info.rss,
            memory_total_bytes=virtual_memory.total,
            cpu_percent=cpu_percent,
            queue_total=queue_total,
            busy_workers=busy_workers,
            worker_total=worker_total,
            chaos_intensity=chaos_intensity,
            chaos_level=chaos_level,
        )
        session.add(metric)
        
        # Clean up old metrics (keep only last 1000) — single bulk DELETE
        count_result = await session.execute(select(func.count(SystemMetrics.id)))
        metric_count = count_result.scalar() or 0
        if metric_count > 1000:
            from sqlalchemy import delete as sa_delete
            old_ids_result = await session.execute(
                select(SystemMetrics.id)
                .order_by(SystemMetrics.timestamp.asc())
                .limit(metric_count - 1000)
            )
            old_ids = [row[0] for row in old_ids_result.all()]
            if old_ids:
                await session.execute(
                    sa_delete(SystemMetrics).where(SystemMetrics.id.in_(old_ids))
                )

        await session.commit()

    await engine.dispose()
    return {"collected": True, "chaos_intensity": chaos_intensity}
