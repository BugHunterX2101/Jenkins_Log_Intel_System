"""
Job Scheduler — receives Git-context payloads, triggers Jenkins builds,
and manages the lifecycle of PipelineRun records.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.pipeline_models import PipelineRun, RunStatus, StageExecution, StageStatus
from app.worker_models import AssignmentStatus
from app.services.jenkinsfile_parser import get_pipeline_stages
from app.services.priority import calculate_pipeline_priority
from app.services.realtime_data import real_pipeline_run_clause

logger = logging.getLogger(__name__)


async def schedule_pipeline(
    session: AsyncSession,
    repo_url: str,
    branch: str,
    commit_sha: str | None = None,
    author: str | None = None,
    triggered_by: str = "api",
    git_token: str | None = None,
    changed_files: list[str] | None = None,
) -> PipelineRun:
    stages = await get_pipeline_stages(
        repo_url, branch,
        token=git_token or getattr(settings, "GITHUB_TOKEN", None),
    )
    if not stages:
        if not settings.ALLOW_SYNTHETIC_PIPELINE_STAGES:
            raise ValueError(
                "No Jenkinsfile stages found for this repository/branch. "
                "Refusing to create synthetic pipeline stages while real-time data mode is enabled."
            )
        stages = ["Checkout", "Build", "Test", "Deploy"]

    job_name = _derive_job_name(repo_url, branch)
    priority = calculate_pipeline_priority(repo_url, branch, changed_files)

    run = PipelineRun(
        repo_url=repo_url,
        branch=branch,
        commit_sha=commit_sha,
        author=author,
        triggered_by=triggered_by,
        jenkins_job_name=job_name,
        status=RunStatus.QUEUED,
        stage_names_csv=",".join(stages) if stages else None,
        scheduling_priority=priority.value,
        priority_reason=priority.reason,
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

    # Dispatch outside the request path. Celery can block while reconnecting to
    # Redis; queueing a run must stay fast so the live UI remains responsive.
    def _dispatch_to_celery() -> None:
        try:
            from app.pipeline_tasks import trigger_jenkins_build
            trigger_jenkins_build.delay(run.id, job_name, branch, commit_sha)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Could not dispatch Celery task: %s", exc)

    threading.Thread(
        target=_dispatch_to_celery,
        daemon=True,
        name=f"celery-dispatch-run-{run.id}",
    ).start()

    return run


async def get_dashboard_snapshot(session: AsyncSession, limit: int = 200) -> dict:
    """Return all PipelineRuns grouped by status for the dashboard."""
    result = await session.execute(
        select(PipelineRun)
        .options(selectinload(PipelineRun.stages))
        .where(real_pipeline_run_clause())
        .order_by(PipelineRun.queued_at.desc())
        .limit(limit)
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
    """Fetch a single run with stages eagerly loaded."""
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
    """Mark the run and worker assignment as started when Jenkins build begins."""
    from app.worker_models import WorkerAssignment
    from sqlalchemy import select

    run = await get_run(session, run_id)
    if not run:
        return
    run.status = RunStatus.IN_PROGRESS
    run.jenkins_build_number = jenkins_build_number
    run.jenkins_build_url = jenkins_build_url
    run.started_at = datetime.now(timezone.utc)
    
    # Also mark the worker assignment as RUNNING to track when actual execution begins
    assignment_result = await session.execute(
        select(WorkerAssignment).where(
            WorkerAssignment.run_id == run_id,
            WorkerAssignment.completed_at.is_(None),
        ).limit(1)
    )
    assignment = assignment_result.scalars().first()
    if isinstance(assignment, WorkerAssignment):
        assignment.status = AssignmentStatus.RUNNING
        assignment.started_at = datetime.now(timezone.utc)
    
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
    Finalise the run when Jenkins reports FINALIZED and release the assigned worker.

    Maps UNSTABLE → FAILED (not ABORTED): Jenkins UNSTABLE means tests passed
    with warnings — it is a build-failure variant, not an abort.

    For non-SUCCESS results, fires LLM root-cause analysis + Slack notification
    in a daemon thread so the DB commit is never blocked.
    """
    import threading
    from app.worker_models import WorkerAssignment
    from app.services.worker_pool import release_worker
    from sqlalchemy import select

    run = await get_run(session, run_id)
    if not run:
        return

    now = datetime.now(timezone.utc)
    run.result = result
    run.completed_at = now
    run.status = (
        RunStatus.COMPLETED if result == "SUCCESS"
        else RunStatus.ABORTED if result == "ABORTED"
        else RunStatus.FAILED   # FAILURE and UNSTABLE both map to FAILED
    )
    if run.started_at:
        run.duration_s = int((now - run.started_at).total_seconds())

    # Mark any still-PENDING/RUNNING stages as SKIPPED
    for stage in run.stages:
        if stage.status in (StageStatus.PENDING, StageStatus.RUNNING):
            stage.status = StageStatus.SKIPPED

    # Capture fields needed for LLM analysis BEFORE the session commits/expires them
    _job_name    = run.jenkins_job_name
    _build_num   = run.jenkins_build_number
    _build_url   = run.jenkins_build_url or (
        f"{settings.JENKINS_URL}/job/{run.jenkins_job_name}/{run.jenkins_build_number}/"
        if run.jenkins_job_name and run.jenkins_build_number else None
    )

    # Release the worker — use first() so retried runs with multiple assignment
    # rows (MultipleResultsFound from scalar_one_or_none) don't crash cancel.
    assignment_result = await session.execute(
        select(WorkerAssignment)
        .where(
            WorkerAssignment.run_id == run_id,
            WorkerAssignment.completed_at.is_(None),
        )
        .limit(1)
    )
    assignment = assignment_result.scalars().first()
    if isinstance(assignment, WorkerAssignment):
        worker_id = assignment.worker_id
        success = (result == "SUCCESS")
        await release_worker(session, worker_id, run_id, success=success)
        logger.info(
            "Released worker %d after build %s for run %d",
            worker_id, result, run_id
        )
    else:
        logger.warning("No worker assignment found for run %d — committing status only", run_id)
        await session.commit()

    # Fire LLM analysis + Slack for every failed/aborted build that has a real build number.
    # Runs in a daemon thread so it never blocks the scheduler tick or webhook handler.
    # _process_async has a duplicate guard so webhook-triggered and scheduler-triggered
    # analyses for the same build don't produce two Slack messages.
    if result != "SUCCESS" and _job_name and _build_num:
        def _run_analysis(job=_job_name, build=_build_num, url=_build_url, res=result):
            import asyncio
            from app.tasks import _process_async
            payload = {
                "name": job,
                "build": {
                    "number": build,
                    "full_url": url or f"{settings.JENKINS_URL}/job/{job}/{build}/",
                    "status": res,
                },
            }
            try:
                loop = asyncio.SelectorEventLoop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_process_async(payload))
            except Exception as exc:
                logger.error("LLM analysis failed for %s #%d: %s", job, build, exc)
            finally:
                loop.close()

        t = threading.Thread(
            target=_run_analysis,
            daemon=True,
            name=f"llm-analysis-run-{run_id}",
        )
        t.start()
        logger.info("LLM analysis thread launched for %s #%d", _job_name, _build_num)


def _derive_job_name(repo_url: str, branch: str) -> str:
    """
    Build a Jenkins multibranch job name from the repo URL.
    Convention: <org>/<repo>/<branch>  (Jenkins multibranch pipeline format).
    """
    path = repo_url.rstrip("/").removesuffix(".git")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}/{branch}"
    return f"{parts[-1]}/{branch}" if parts else f"unknown/{branch}"


def serialise_run(run: PipelineRun) -> dict:
    scheduling_priority = getattr(run, "scheduling_priority", 6)
    priority_reason = getattr(run, "priority_reason", None)
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
        "scheduling_priority": scheduling_priority,
        "priority_label": (
            f"P{scheduling_priority}" if not priority_reason
            else f"P{scheduling_priority} - {priority_reason}"
        ),
        "priority_reason": priority_reason,
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
