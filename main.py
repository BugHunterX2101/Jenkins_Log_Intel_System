"""
Jenkins Log Intelligence Engine — FastAPI application factory v1.2
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import webhook
from app.routers import jobs
from app.routers import workers
from app.routers import github_webhook
from app.models import Base


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
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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

app.include_router(webhook.router)
app.include_router(github_webhook.router)
app.include_router(jobs.router)
app.include_router(workers.router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": "1.2.0"}
