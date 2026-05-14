"""
Workers Router — REST endpoints for the CI worker pool.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.worker_models import Worker, WorkerAssignment, WorkerStatus, AssignmentStatus
from app.pipeline_models import PipelineRun, RunStatus
from app.services.worker_pool import seed_workers, serialise_worker

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("", summary="List all workers")
async def list_workers(session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(select(Worker).order_by(Worker.id))
    workers = result.scalars().all()
    return {
        "workers": [serialise_worker(w) for w in workers],
        "summary": {
            "total":   len(workers),
            "idle":    sum(1 for w in workers if w.status == WorkerStatus.IDLE),
            "busy":    sum(1 for w in workers if w.status == WorkerStatus.BUSY),
            "offline": sum(1 for w in workers if w.status == WorkerStatus.OFFLINE),
        },
    }


@router.get("/{worker_id}", summary="Worker detail")
async def worker_detail(
    worker_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    ar = await session.execute(
        select(WorkerAssignment)
        .where(WorkerAssignment.worker_id == worker_id)
        .order_by(WorkerAssignment.assigned_at.desc())
        .limit(10)
    )
    assignments = ar.scalars().all()

    return {
        **serialise_worker(worker),
        "recent_assignments": [
            {
                "run_id":       a.run_id,
                "status":       a.status.value,
                "assigned_at":  a.assigned_at.isoformat() if a.assigned_at else None,
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                "duration_s":   a.duration_s,
                "result":       a.result,
            }
            for a in assignments
        ],
    }


@router.post("/{worker_id}/offline", summary="Take worker offline")
async def set_offline(
    worker_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    worker.status = WorkerStatus.OFFLINE
    await session.commit()
    return {"worker_id": worker_id, "status": "OFFLINE"}


@router.post("/{worker_id}/online", summary="Bring worker online")
async def set_online(
    worker_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    worker.status = WorkerStatus.IDLE
    worker.load   = 0.0
    await session.commit()
    return {"worker_id": worker_id, "status": "IDLE"}


@router.post("/{worker_id}/reset", summary="Force-reset a BUSY worker to IDLE")
async def reset_worker(
    worker_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    assign_result = await session.execute(
        select(WorkerAssignment).where(
            WorkerAssignment.worker_id == worker_id,
            WorkerAssignment.completed_at.is_(None),
        )
    )
    reverted_runs: list[int] = []
    now = datetime.now(timezone.utc)
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
            reverted_runs.append(run.id)
        assignment.status = AssignmentStatus.FAILED
        assignment.completed_at = now
        assignment.result = "MANUAL_RESET"

    old_status = worker.status.value
    worker.status = WorkerStatus.IDLE
    worker.load = 0.0
    worker.current_job = None
    worker.last_heartbeat = now
    await session.commit()

    return {
        "worker_id": worker_id,
        "previous_status": old_status,
        "status": "IDLE",
        "reverted_runs": reverted_runs,
    }


@router.post("/recover", summary="Bulk-recover all stale workers")
async def recover_all_workers() -> dict:
    from app.scheduler import _recover_stale_workers
    from app.db import get_session_factory
    recovered = await _recover_stale_workers(get_session_factory())
    return {"recovered": recovered}


@router.post("/seed", summary="Seed default workers")
async def seed(session: AsyncSession = Depends(get_session)) -> dict:
    if not settings.AUTO_SEED_WORKERS:
        raise HTTPException(
            status_code=403,
            detail="Default worker seeding is disabled so dashboards only show configured workers.",
        )
    await seed_workers(session)
    return {"seeded": True}
