"""
Job Scheduler — receives Git-context payloads, triggers Jenkins builds,
and manages the lifecycle of PipelineRun records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.pipeline_models import PipelineRun, RunStatus, StageExecution, StageStatus
from app.services.jenkinsfile_parser import get_pipeline_stages

logger = logging.getLogger(__name__)


async def schedule_pipeline(
    session: AsyncSession,
    repo_url: str,
    branch: str,
    commit_sha: str | None = None,
    author: str | None = None,
    triggered_by: str = "api",
    git_token: str | None = None,
) -> PipelineRun:
    stages = await get_pipeline_stages(
        repo_url, branch,
        token=git_token or getattr(settings, "GITHUB_TOKEN", None),
    )

    job_name = _derive_job_name(repo_url, branch)

    run = PipelineRun(
        repo_url=repo_url,
        branch=branch,
        commit_sha=commit_sha,
        author=author,
        triggered_by=triggered_by,
        jenkins_job_name=job_name,
        status=RunStatus.QUEUED,
        stage_names_csv=",".join(stages) if stages else None,
    )
    session.add(run)
    await session.flush()

    for idx, stage_name in enumerate(stages):
        session.add(
            StageExecution(
                run_id=run.id,
                order=idx,
                name=stage_name,
                status=StageStatus.PENDING,
            )
        )

    await session.commit()
    await session.refresh(run)

    logger.info("Scheduled PipelineRun id=%d for %s@%s", run.id, repo_url, branch)

    # FIX: Wrap Celery dispatch so missing broker doesn't abort the whole request
    try:
        from app.pipeline_tasks import trigger_jenkins_build
        trigger_jenkins_build.delay(run.id, job_name, branch, commit_sha)
    except Exception as exc:
        logger.warning("Could not dispatch Celery task: %s", exc)

    return run


async def get_dashboard_snapshot(session: AsyncSession) -> dict:
    """
    Return all PipelineRuns grouped by status for the dashboard.

    FIX: Use selectinload to eagerly load stages, avoiding async lazy-load
    MissingGreenlet errors that occur when accessing run.stages after the
    query result is returned.
    """
    result = await session.execute(
        select(PipelineRun)
        .options(selectinload(PipelineRun.stages))
        .order_by(PipelineRun.queued_at.desc())
    )
    runs = result.scalars().unique().all()

    snapshot: dict[str, list] = {
        "QUEUED": [],
        "IN_PROGRESS": [],
        "COMPLETED": [],
        "FAILED": [],
        "ABORTED": [],
    }

    for run in runs:
        bucket = run.status.value if run.status.value in snapshot else "COMPLETED"
        snapshot[bucket].append(serialise_run(run))

    return snapshot


async def get_run(session: AsyncSession, run_id: int) -> PipelineRun | None:
    """
    FIX: Use selectinload so run.stages is available without triggering
    async lazy-loading (which raises MissingGreenlet in SQLAlchemy async).
    """
    result = await session.execute(
        select(PipelineRun)
        .options(selectinload(PipelineRun.stages))
        .where(PipelineRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def on_build_started(
    session: AsyncSession,
    run_id: int,
    jenkins_build_number: int,
    jenkins_build_url: str,
) -> None:
    run = await get_run(session, run_id)
    if not run:
        return
    run.status = RunStatus.IN_PROGRESS
    run.jenkins_build_number = jenkins_build_number
    run.jenkins_build_url = jenkins_build_url
    run.started_at = datetime.now(timezone.utc)
    await session.commit()


async def on_stage_started(
    session: AsyncSession,
    run_id: int,
    stage_name: str,
) -> None:
    result = await session.execute(
        select(StageExecution).where(
            StageExecution.run_id == run_id,
            StageExecution.name == stage_name,
        )
    )
    stage = result.scalar_one_or_none()
    if stage:
        stage.status = StageStatus.RUNNING
        stage.started_at = datetime.now(timezone.utc)
        await session.commit()


async def on_stage_completed(
    session: AsyncSession,
    run_id: int,
    stage_name: str,
    success: bool,
    log_excerpt: str | None = None,
) -> None:
    result = await session.execute(
        select(StageExecution).where(
            StageExecution.run_id == run_id,
            StageExecution.name == stage_name,
        )
    )
    stage = result.scalar_one_or_none()
    if stage:
        now = datetime.now(timezone.utc)
        stage.status = StageStatus.SUCCESS if success else StageStatus.FAILED
        stage.completed_at = now
        stage.log_excerpt = log_excerpt
        if stage.started_at:
            stage.duration_s = int((now - stage.started_at).total_seconds())
        await session.commit()


async def on_build_completed(
    session: AsyncSession,
    run_id: int,
    result: str,
) -> None:
    """
    Finalise the run when Jenkins reports FINALIZED.

    FIX: Map UNSTABLE -> FAILED (not ABORTED). Jenkins UNSTABLE means tests
    passed but with warnings — it is a build failure variant, not an abort.
    The original catch-all mapped it to ABORTED which is semantically wrong
    and misleading on the dashboard.
    """
    run = await get_run(session, run_id)
    if not run:
        return
    run.result = result
    run.completed_at = datetime.now(timezone.utc)
    run.status = (
        RunStatus.COMPLETED if result == "SUCCESS"
        else RunStatus.ABORTED if result == "ABORTED"
        else RunStatus.FAILED   # FAILURE and UNSTABLE both map to FAILED
    )
    if run.started_at:
        run.duration_s = int((run.completed_at - run.started_at).total_seconds())

    # Mark any still-PENDING/RUNNING stages as SKIPPED
    for stage in run.stages:
        if stage.status in (StageStatus.PENDING, StageStatus.RUNNING):
            stage.status = StageStatus.SKIPPED

    await session.commit()


def _derive_job_name(repo_url: str, branch: str) -> str:
    """
    Build a Jenkins multibranch job name from the repo URL.
    Convention: <org>/<repo>/<branch>  (Jenkins multibranch pipeline format).
    """
    path = repo_url.rstrip("/").rstrip(".git")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}/{branch}"
    return f"{parts[-1]}/{branch}" if parts else f"unknown/{branch}"


def serialise_run(run: PipelineRun) -> dict:
    return {
        "id": run.id,
        "repo_url": run.repo_url,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "author": run.author,
        "triggered_by": run.triggered_by,
        "jenkins_job_name": run.jenkins_job_name,
        "jenkins_build_number": run.jenkins_build_number,
        "jenkins_build_url": run.jenkins_build_url,
        "status": run.status.value,
        "result": run.result,
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_s": run.duration_s,
        "stages": [_serialise_stage(s) for s in (run.stages or [])],
    }


def _serialise_stage(stage: StageExecution) -> dict:
    return {
        "id": stage.id,
        "order": stage.order,
        "name": stage.name,
        "status": stage.status.value,
        "started_at": stage.started_at.isoformat() if stage.started_at else None,
        "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
        "duration_s": stage.duration_s,
        "log_excerpt": stage.log_excerpt,
    }
