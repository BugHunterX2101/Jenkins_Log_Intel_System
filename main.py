"""
Jenkins Log Intelligence Engine — FastAPI application factory v1.2
"""

import asyncio
import os
import logging
import random
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import get_engine, get_session_factory
from app.routers import webhook
from app.routers import jobs
from app.routers import workers
from app.routers import github_webhook
from app.routers import ui
from app.models import Base

_sched_logger = logging.getLogger("scheduler.loop")


def _background_loops_enabled() -> bool:
    # Force-disabled by default to keep the test/dev server lightweight.
    # In-process scheduler and random arrival loops are resource-heavy and
    # interfere with functional tests; enable them only with a deliberate
    # code change or explicit runtime orchestration.
    return False


async def _scheduler_loop() -> None:
    """Run scheduler_tick every 5 s inside the FastAPI process (no Celery needed)."""
    from app.scheduler import _scheduler_tick_async
    while True:
        try:
            await _scheduler_tick_async(use_celery=False)
        except Exception as exc:
            _sched_logger.warning("scheduler tick error: %s", exc)
        await asyncio.sleep(5)


async def _random_arrival_loop() -> None:
    """Inject synthetic pipeline runs periodically (mirrors the Celery beat task)."""
    from app.scheduler import _enqueue_synthetic, _SYNTHETIC_REPOS
    await asyncio.sleep(20)          # initial delay so workers are ready first
    while True:
        await asyncio.sleep(45)
        if random.random() <= 0.6:
            repo_url, branch = random.choice(_SYNTHETIC_REPOS)
            author = random.choice(["alice", "bob", "carol", "dave", "ci-bot"])
            sha = "".join(random.choices("0123456789abcdef", k=40))
            try:
                await _enqueue_synthetic(repo_url, branch, sha, author)
                _sched_logger.info("Random arrival injected: %s@%s", repo_url, branch)
            except Exception as exc:
                _sched_logger.warning("random arrival error: %s", exc)


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def _serve_page(filename: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / filename)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables and seed workers on startup."""
    try:
        from app.services.worker_pool import seed_workers
        import app.pipeline_models  # noqa: F401
        import app.worker_models  # noqa: F401

        # Use the global shared engine from app.db
        engine = get_engine()
        session_factory = get_session_factory()
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Add current_job column if it doesn't exist yet (existing DBs)
            from sqlalchemy import text
            await conn.execute(text(
                "ALTER TABLE workers ADD COLUMN IF NOT EXISTS current_job VARCHAR(256)"
            ))
            # Backfill current_job for workers that were BUSY before the column existed
            await conn.execute(text("""
                UPDATE workers w
                SET current_job = pr.jenkins_job_name
                FROM worker_assignments wa
                JOIN pipeline_runs pr ON pr.id = wa.run_id
                WHERE wa.worker_id = w.id
                  AND w.status = 'BUSY'
                  AND w.current_job IS NULL
                  AND wa.completed_at IS NULL
            """))
        async with session_factory() as session:
            await seed_workers(session)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Worker seed skipped: %s", e)

    tick_task = None
    arrival_task = None
    if _background_loops_enabled():
        # Start background scheduler loops (no Celery / Redis required)
        tick_task = asyncio.create_task(_scheduler_loop())
        arrival_task = asyncio.create_task(_random_arrival_loop())

    yield

    tasks = [task for task in (tick_task, arrival_task) if task is not None]
    for task in tasks:
        task.cancel()
    if tasks:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass


app = FastAPI(
    title="Jenkins Log Intelligence Engine",
    description=(
        "CI/CD intelligence platform: intercepts failed builds, analyses logs, "
        "schedules jobs across a simulated worker pool, and streams live "
        "pipeline progress to the dashboard."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")


# ── HTML page routes (must be registered BEFORE API routers to avoid conflicts) ──

@app.get("/", include_in_schema=False)
async def frontend_index() -> FileResponse:
    return _serve_page("index.html")


@app.get("/backend", include_in_schema=False)
@app.get("/backend.html", include_in_schema=False)
async def frontend_backend() -> FileResponse:
    return _serve_page("backend.html")


@app.get("/queue", include_in_schema=False)
@app.get("/queue.html", include_in_schema=False)
async def frontend_queue() -> FileResponse:
    return _serve_page("queue.html")


@app.get("/scheduler", include_in_schema=False)
@app.get("/scheduler.html", include_in_schema=False)
async def frontend_scheduler() -> FileResponse:
    return _serve_page("scheduler.html")


@app.get("/simulation", include_in_schema=False)
@app.get("/simulation.html", include_in_schema=False)
async def frontend_simulation() -> FileResponse:
    return _serve_page("simulation.html")


@app.get("/webhooks", include_in_schema=False)
@app.get("/webhooks.html", include_in_schema=False)
async def frontend_webhooks() -> FileResponse:
    return _serve_page("webhooks.html")


@app.get("/workers", include_in_schema=False)
@app.get("/workers.html", include_in_schema=False)
async def frontend_workers() -> FileResponse:
    return _serve_page("workers.html")


@app.get("/explorer", include_in_schema=False)
@app.get("/explorer.html", include_in_schema=False)
async def frontend_explorer() -> FileResponse:
    return _serve_page("explorer.html")


@app.get("/settings", include_in_schema=False)
@app.get("/settings.html", include_in_schema=False)
async def frontend_settings() -> FileResponse:
    return _serve_page("settings.html")


# ── API routers ──

app.include_router(webhook.router)
app.include_router(github_webhook.router)
app.include_router(jobs.router)
app.include_router(workers.router)
app.include_router(ui.router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": "1.2.0"}
