"""
Workers Router — REST endpoints for the simulated worker pool.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.worker_models import Worker, WorkerAssignment, WorkerStatus
from app.services.worker_pool import seed_workers, serialise_worker

router = APIRouter(prefix="/api/workers", tags=["workers"])


def _make_session():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_SF = _make_session()


async def _get_session():
    async with _SF() as session:
        yield session


@router.get("", summary="List all workers")
async def list_workers(session: AsyncSession = Depends(_get_session)) -> dict:
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
    session: AsyncSession = Depends(_get_session),
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
    session: AsyncSession = Depends(_get_session),
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
    session: AsyncSession = Depends(_get_session),
) -> dict:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    worker.status = WorkerStatus.IDLE
    worker.load   = 0.0
    await session.commit()
    return {"worker_id": worker_id, "status": "IDLE"}


@router.post("/seed", summary="Seed default workers")
async def seed(session: AsyncSession = Depends(_get_session)) -> dict:
    await seed_workers(session)
    return {"seeded": True}
