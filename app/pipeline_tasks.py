"""
Pipeline Celery Tasks — background workers for:
  - Triggering a Jenkins build from a PipelineRun record.
  - Polling Jenkins pipeline stage progress.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx
from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "pipeline_manager",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.task_serializer  = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content   = ["json"]

# Module-level stubs so tests can patch scheduler callbacks by name:
#   patch("app.pipeline_tasks.on_stage_started", new_callable=AsyncMock)
# Without these, the names only exist inside _sync_stages local scope.
on_stage_started  = None
on_stage_completed = None
on_build_completed = None
get_run           = None


@celery_app.task(
    name="pipeline_tasks.trigger_jenkins_build",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def trigger_jenkins_build(
    self,
    run_id: int,
    job_name: str,
    branch: str,
    commit_sha: str | None = None,
) -> dict:
    try:
        build_number, build_url = asyncio.run(
            _trigger_jenkins(job_name, branch, commit_sha)
        )
        asyncio.run(_mark_started(run_id, build_number, build_url))
        poll_pipeline_stages.apply_async(
            args=[run_id, job_name, build_number],
            countdown=10,
        )
        return {"run_id": run_id, "build_number": build_number}
    except Exception as exc:
        logger.error("Failed to trigger Jenkins build for run %d: %s", run_id, exc)
        raise self.retry(exc=exc)


async def _trigger_jenkins(
    job_name: str,
    branch: str,
    commit_sha: str | None,
) -> tuple[int, str]:
    encoded_job = job_name.replace("/", "/job/")
    url = f"{settings.JENKINS_URL}/job/{encoded_job}/buildWithParameters"
    auth = (settings.JENKINS_USER, settings.JENKINS_TOKEN)

    params: dict = {}
    if commit_sha:
        params["GIT_COMMIT"] = commit_sha
    params["BRANCH"] = branch

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, auth=auth, params=params)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Jenkins trigger returned {resp.status_code}: {resp.text[:200]}"
            )
        queue_url = resp.headers.get("Location", "")

    build_number, build_url = await _resolve_queue_item(queue_url, auth)
    return build_number, build_url


async def _resolve_queue_item(
    queue_url: str,
    auth: tuple[str, str],
    max_wait: int = 60,
) -> tuple[int, str]:
    if not queue_url:
        return (0, f"{settings.JENKINS_URL}/")

    api_url = queue_url.rstrip("/") + "/api/json"
    deadline = time.monotonic() + max_wait

    async with httpx.AsyncClient(timeout=30) as client:
        while time.monotonic() < deadline:
            resp = await client.get(api_url, auth=auth)
            if resp.status_code == 200:
                data = resp.json()
                exe = data.get("executable")
                if exe:
                    return exe["number"], exe["url"]
            await asyncio.sleep(3)

    return (0, f"{settings.JENKINS_URL}/")


async def _mark_started(run_id: int, build_number: int, build_url: str) -> None:
    from app.services.job_scheduler import on_build_started

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await on_build_started(session, run_id, build_number, build_url)


@celery_app.task(
    name="pipeline_tasks.poll_pipeline_stages",
    bind=True,
    max_retries=60,
    default_retry_delay=10,
)
def poll_pipeline_stages(
    self,
    run_id: int,
    job_name: str,
    build_number: int,
) -> dict:
    try:
        done = asyncio.run(_sync_stages(run_id, job_name, build_number))
        if not done:
            raise self.retry(countdown=10)
        return {"run_id": run_id, "done": True}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error("Stage poll exhausted retries for run %d", run_id)
            return {"run_id": run_id, "done": False, "error": str(exc)}
        raise self.retry(exc=exc, countdown=10)


async def _sync_stages(run_id: int, job_name: str, build_number: int) -> bool:
    """
    Fetch Jenkins Workflow Stage API and reconcile with StageExecution rows.

    FIX: The original code opened the httpx.AsyncClient in one 'async with' block,
    closed it, then tried to reuse the closed client inside a later 'async with
    Session()' block for fetching stage logs. This would raise
    'RuntimeError: Cannot send a request, as the client has been closed.'

    Fixed by keeping a single httpx.AsyncClient open for the entire function,
    including the stage-log fetches.
    """
    from app.services.job_scheduler import (
        on_stage_started as _on_stage_started,
        on_stage_completed as _on_stage_completed,
        on_build_completed as _on_build_completed,
        get_run as _get_run,
    )
    import app.pipeline_tasks as _pt
    # Use module-level stub if it's been patched by tests (not None); else fall
    # back to the real function imported above. getattr() alone would return the
    # None stub value and never reach the default — use `or` like worker_pool.py.
    _on_ss  = getattr(_pt, "on_stage_started",  None) or _on_stage_started
    _on_sc  = getattr(_pt, "on_stage_completed", None) or _on_stage_completed
    _on_bc  = getattr(_pt, "on_build_completed", None) or _on_build_completed
    _gr     = getattr(_pt, "get_run",            None) or _get_run

    encoded_job = job_name.replace("/", "/job/")
    api_url = (
        f"{settings.JENKINS_URL}/job/{encoded_job}/{build_number}"
        f"/wfapi/describe"
    )
    auth = (settings.JENKINS_USER, settings.JENKINS_TOKEN)

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # FIX: Keep the client open for the entire function so stage-log fetches
    # (inside the session block below) can still use it.
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(api_url, auth=auth)
            if resp.status_code != 200:
                return False
            data = resp.json()
        except httpx.RequestError:
            return False

        build_status = data.get("status", "")
        jenkins_stages = data.get("stages", [])

        async with Session() as session:
            for js in jenkins_stages:
                name   = js.get("name", "")
                status = js.get("status", "")

                if status == "IN_PROGRESS":
                    await _on_ss(session, run_id, name)

                elif status in ("SUCCESS", "FAILED", "UNSTABLE"):
                    log_excerpt = None
                    try:
                        log_url = (
                            f"{settings.JENKINS_URL}/job/{encoded_job}/{build_number}"
                            f"/execution/node/{js.get('id', '')}/wfapi/log"
                        )
                        # FIX: client is still open here (within the outer async with)
                        log_resp = await client.get(log_url, auth=auth)
                        if log_resp.status_code == 200:
                            log_excerpt = log_resp.json().get("text", "")[-1000:]
                    except Exception:
                        pass

                    await _on_sc(
                        session, run_id, name,
                        success=(status == "SUCCESS"),
                        log_excerpt=log_excerpt,
                    )

            if build_status in ("SUCCESS", "FAILURE", "ABORTED", "UNSTABLE"):
                await _on_bc(session, run_id, build_status)
                return True

    return False
