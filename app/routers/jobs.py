"""
Jobs Router — REST endpoints for the Job Scheduler and Pipeline Manager.
"""

from __future__ import annotations

from typing import Optional

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

logger = logging.getLogger(__name__)
from app.services.job_scheduler import (
    get_dashboard_snapshot,
    get_run,
    on_stage_completed,
    on_stage_started,
    schedule_pipeline,
    serialise_run,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


class TriggerRequest(BaseModel):
    repo_url:     str          = Field(..., description="HTTPS clone URL of the repository")
    branch:       str          = Field(..., description="Branch name to build")
    commit_sha:   Optional[str] = Field(None, description="Commit SHA (optional)")
    author:       Optional[str] = Field(None, description="Who authored the commit")
    triggered_by: str          = Field("api", description="System/user that initiated the trigger")
    git_token:    Optional[str] = Field(None, description="Git token for private repo Jenkinsfile fetch")
    changed_files: list[str]   = Field(default_factory=list, description="Files changed by the push")


class StageEventRequest(BaseModel):
    stage_name: str
    event:      str           # "started" | "completed" | "failed"
    log_excerpt: Optional[str] = None


@router.post("/trigger", status_code=201, summary="Trigger a new pipeline run")
async def trigger_pipeline(
    body: TriggerRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        run = await schedule_pipeline(
            session=session,
            repo_url=body.repo_url,
            branch=body.branch,
            commit_sha=body.commit_sha,
            author=body.author,
            triggered_by=body.triggered_by,
            git_token=body.git_token,
            changed_files=body.changed_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "run_id": run.id,
        "status": run.status.value,
        "jenkins_job_name": run.jenkins_job_name,
        "stages": run.stage_names,
        "scheduling_priority": run.scheduling_priority,
        "priority_reason": run.priority_reason,
        "message": "Pipeline queued successfully",
    }


_EMPTY_SNAPSHOT = {"QUEUED": [], "IN_PROGRESS": [], "COMPLETED": [], "FAILED": [], "ABORTED": []}


@router.get("", summary="Dashboard snapshot")
async def dashboard(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        return await get_dashboard_snapshot(session)
    except Exception as exc:
        logger.error("get_dashboard_snapshot failed: %s", exc, exc_info=True)
        return _EMPTY_SNAPSHOT


@router.get("/dashboard", summary="Dashboard snapshot (alias)", include_in_schema=False)
async def dashboard_alias(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        return await get_dashboard_snapshot(session)
    except Exception as exc:
        logger.error("get_dashboard_snapshot (alias) failed: %s", exc, exc_info=True)
        return _EMPTY_SNAPSHOT


@router.get("/{run_id:int}", summary="Single run detail")
async def run_detail(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        run = await get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"PipelineRun {run_id} not found")
        return serialise_run(run)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to retrieve run %d: %s", run_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error retrieving pipeline run")


@router.post("/{run_id:int}/retry", summary="Manually retry a failed pipeline run")
async def retry_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    from sqlalchemy import select
    from app.pipeline_models import PipelineRun, RunStatus

    result = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"PipelineRun {run_id} not found")
    if run.status != RunStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not in FAILED status (current: {run.status.value})",
        )
    if run.retry_count >= run.max_retries:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} has exhausted max retries ({run.max_retries})",
        )

    run.retry_count += 1
    run.status = RunStatus.QUEUED
    run.started_at = None
    run.completed_at = None
    run.retry_after = None
    await session.commit()
    logger.info("Manual retry queued for run %d (attempt %d/%d)", run_id, run.retry_count, run.max_retries)
    return {
        "retried": run_id,
        "status": "QUEUED",
        "retry_count": run.retry_count,
        "max_retries": run.max_retries,
    }


@router.post("/{run_id:int}/stage-event", summary="Receive stage progress event")
async def stage_event(
    run_id: int,
    body: StageEventRequest,
    session: AsyncSession = Depends(get_session),
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
