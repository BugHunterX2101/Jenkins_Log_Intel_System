"""
Jenkins Log Intelligence Engine — FastAPI application factory v1.2
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import webhook
from app.routers import jobs
from app.routers import workers
from app.routers import github_webhook
from app.routers import ui
from app.models import Base


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def _serve_page(filename: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / filename)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables and seed workers on startup."""
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from app.config import settings
        from app.services.worker_pool import seed_workers
        import app.pipeline_models  # noqa: F401
        import app.worker_models  # noqa: F401

        engine  = create_async_engine(settings.DATABASE_URL, echo=False)
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Add current_job column if it doesn't exist yet (existing DBs)
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
        async with Session() as session:
            await seed_workers(session)
        await engine.dispose()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Worker seed skipped: %s", e)

    yield


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
