"""
Scheduler Loop — the Jenkins Master brain.
"""
from __future__ import annotations

import asyncio
import logging
import random

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "scheduler",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "scheduler-tick": {
            "task": "app.scheduler.scheduler_tick",
            "schedule": 5.0,
        },
        "random-job-arrival": {
            "task": "app.scheduler.random_job_arrival",
            "schedule": 45.0,
        },
        "worker-load-drift": {
            "task": "app.scheduler.worker_load_drift",
            "schedule": 15.0,
        },
    },
)


@celery_app.task(name="app.scheduler.scheduler_tick")
def scheduler_tick() -> dict:
    return asyncio.run(_scheduler_tick_async())


async def _scheduler_tick_async() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, update
    from app.pipeline_models import PipelineRun, RunStatus
    from app.services.worker_pool import assign_worker, detect_language

    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    assigned_count = 0

    async with Session() as session:
        result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.status == RunStatus.QUEUED)
            .order_by(PipelineRun.queued_at.asc())
        )
        queued_runs = result.scalars().all()

    for run in queued_runs:
        stage_names = run.stage_names

        async with Session() as session:
            # FIX: Race condition — two concurrent scheduler ticks could both
            # read the same QUEUED run and dispatch it to two workers.
            # Solution: atomically claim the run by transitioning it to
            # IN_PROGRESS within the same transaction as assign_worker.
            # We use an UPDATE with a WHERE clause to ensure only one tick
            # successfully claims it (the other will see 0 rows updated).
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

            if claim_result.rowcount == 0:
                # Another tick already claimed this run — skip it
                logger.debug("Scheduler: run %d already claimed, skipping", run.id)
                continue

            language = detect_language(run.repo_url, stage_names)
            worker   = await assign_worker(session, run.id, language)

        if worker:
            execute_pipeline_run.delay(
                run_id=run.id,
                worker_id=worker.id,
                stage_names=stage_names,
                worker_name=worker.name,
            )
            logger.info(
                "Scheduler: dispatched run %d to worker %s (lang=%s)",
                run.id, worker.name, language.value,
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
    from app.services.worker_pool import simulate_execution

    if not stage_names:
        stage_names = ["Checkout", "Build", "Test", "Deploy"]

    return await simulate_execution(
        run_id=run_id,
        worker_id=worker_id,
        stage_names=stage_names,
        db_url=settings.DATABASE_URL,
    )


_SYNTHETIC_REPOS = [
    ("https://github.com/acme/auth-service",    "main"),
    ("https://github.com/acme/api-gateway",     "develop"),
    ("https://github.com/acme/payment-service", "main"),
    ("https://github.com/acme/data-pipeline",   "feature/etl-v2"),
    ("https://github.com/acme/frontend-app",    "main"),
]


@celery_app.task(name="app.scheduler.random_job_arrival")
def random_job_arrival() -> dict:
    if random.random() > 0.6:
        return {"injected": False, "reason": "random skip"}

    repo_url, branch = random.choice(_SYNTHETIC_REPOS)
    author = random.choice(["alice", "bob", "carol", "dave", "ci-bot"])

    import string
    commit_sha = "".join(random.choices("0123456789abcdef", k=40))

    asyncio.run(_enqueue_synthetic(repo_url, branch, commit_sha, author))
    logger.info("Random arrival: injected %s@%s", repo_url, branch)
    return {"injected": True, "repo": repo_url, "branch": branch}


async def _enqueue_synthetic(repo_url, branch, commit_sha, author):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.job_scheduler import schedule_pipeline

    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        await schedule_pipeline(
            session=session,
            repo_url=repo_url,
            branch=branch,
            commit_sha=commit_sha,
            author=author,
            triggered_by="random-arrival",
        )
    await engine.dispose()


@celery_app.task(name="app.scheduler.worker_load_drift")
def worker_load_drift() -> dict:
    return asyncio.run(_drift_async())


async def _drift_async() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.worker_models import Worker, WorkerStatus

    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(
            select(Worker).where(Worker.status == WorkerStatus.IDLE)
        )
        workers = result.scalars().all()
        for w in workers:
            w.load = max(0.0, min(0.3, w.load + random.uniform(-0.05, 0.05)))
        await session.commit()

    await engine.dispose()
    return {"drifted": len(workers)}
