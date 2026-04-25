"""
Jobs Router — REST endpoints for the Job Scheduler and Pipeline Manager.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.services.job_scheduler import (
    get_dashboard_snapshot,
    get_run,
    on_build_completed,
    on_stage_completed,
    on_stage_started,
    schedule_pipeline,
    _serialise_run,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _make_session_factory():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_SessionFactory = _make_session_factory()


async def _get_session():
    async with _SessionFactory() as session:
        yield session


class TriggerRequest(BaseModel):
    repo_url:     str          = Field(..., description="HTTPS clone URL of the repository")
    branch:       str          = Field(..., description="Branch name to build")
    commit_sha:   Optional[str] = Field(None, description="Commit SHA (optional)")
    author:       Optional[str] = Field(None, description="Who authored the commit")
    triggered_by: str          = Field("api", description="System/user that initiated the trigger")
    git_token:    Optional[str] = Field(None, description="Git token for private repo Jenkinsfile fetch")


class StageEventRequest(BaseModel):
    stage_name: str
    event:      str           # "started" | "completed" | "failed"
    log_excerpt: Optional[str] = None


@router.post("/trigger", status_code=201, summary="Trigger a new pipeline run")
async def trigger_pipeline(
    body: TriggerRequest,
    session: AsyncSession = Depends(_get_session),
) -> dict:
    run = await schedule_pipeline(
        session=session,
        repo_url=body.repo_url,
        branch=body.branch,
        commit_sha=body.commit_sha,
        author=body.author,
        triggered_by=body.triggered_by,
        git_token=body.git_token,
    )
    return {
        "run_id": run.id,
        "status": run.status.value,
        "jenkins_job_name": run.jenkins_job_name,
        "stages": run.stage_names,
        "message": "Pipeline queued successfully",
    }


@router.get("", summary="Dashboard snapshot")
async def dashboard(session: AsyncSession = Depends(_get_session)) -> dict:
    return await get_dashboard_snapshot(session)


@router.get("/{run_id}", summary="Single run detail")
async def run_detail(
    run_id: int,
    session: AsyncSession = Depends(_get_session),
) -> dict:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"PipelineRun {run_id} not found")
    return _serialise_run(run)


@router.post("/{run_id}/stage-event", summary="Receive stage progress event")
async def stage_event(
    run_id: int,
    body: StageEventRequest,
    session: AsyncSession = Depends(_get_session),
) -> dict:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"PipelineRun {run_id} not found")

    if body.event == "started":
        await on_stage_started(session, run_id, body.stage_name)

    elif body.event in ("completed", "failed"):
        await on_stage_completed(
            session,
            run_id,
            body.stage_name,
            success=(body.event == "completed"),
            log_excerpt=body.log_excerpt,
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown event: {body.event!r}")

    return {"acknowledged": True}
