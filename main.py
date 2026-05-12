"""
Jenkins Log Intelligence Engine — FastAPI application factory v1.2
"""

import asyncio
import os
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import get_engine, get_session_factory
from app.routers import webhook
from app.routers import jobs
from app.routers import workers
from app.routers import github_webhook
from app.routers.github_webhook import github_alias_router
from app.routers import ui
from app.models import Base

_sched_logger = logging.getLogger("scheduler.loop")


async def _scheduler_loop() -> None:
    """Run scheduler_tick every 5 s inside the FastAPI process (no Celery needed)."""
    from app.scheduler import _scheduler_tick_async
    while True:
        try:
            await _scheduler_tick_async(use_celery=False)
        except Exception as exc:
            _sched_logger.warning("scheduler tick error: %s", exc)
        await asyncio.sleep(5)


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def _serve_page(filename: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / filename)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create database tables and seed workers on startup."""
    try:
        from app.services.worker_pool import seed_workers
        from app import pipeline_models as _pm  # noqa: F401
        from app import worker_models as _wm    # noqa: F401

        # Use the global shared engine from app.db
        engine = get_engine()
        session_factory = get_session_factory()
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Add current_job column if it doesn't exist yet (existing DBs).
            # The IF NOT EXISTS syntax is PostgreSQL-only; silently skip on other dialects.
            from sqlalchemy import text
            dialect = engine.dialect.name
            try:
                if dialect == "postgresql":
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
                # For SQLite and other dialects: current_job is defined in the model,
                # so create_all already created it — no ALTER TABLE needed.
            except Exception as alter_err:
                import logging
                logging.getLogger(__name__).warning("ALTER TABLE skipped: %s", alter_err)
        async with session_factory() as session:
            await seed_workers(session)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Worker seed skipped: %s", e)

    tick_task = asyncio.create_task(_scheduler_loop())

    yield

    tick_task.cancel()
    await asyncio.gather(tick_task, return_exceptions=True)


app = FastAPI(
    title="Jenkins Log Intelligence Engine",
    description=(
        "CI/CD intelligence platform: intercepts failed builds, analyses logs, "
        "schedules jobs across a worker pool, and streams live "
        "pipeline progress to the dashboard."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def track_http_requests(request: Request, call_next):
    """Capture real latency + status for every API call — powers Live Request Feed."""
    from app.request_log import log_request
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    # Skip static assets and noisy health pings to keep the feed meaningful
    if not path.startswith("/assets") and path not in ("/favicon.ico",):
        log_request(request.method, path, response.status_code, latency_ms)
    return response


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
app.include_router(github_alias_router)   # /github-webhook/ — ngrok real webhook path
app.include_router(jobs.router)
app.include_router(workers.router)
app.include_router(ui.router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe — checks real DB connectivity."""
    from app.utils import check_db_health
    db_ok = await check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.2.0",
        "db": "ok" if db_ok else "error",
    }
