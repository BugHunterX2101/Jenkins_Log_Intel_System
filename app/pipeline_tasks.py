"""
Pipeline Celery Tasks — background workers for:
  - Triggering a Jenkins build from a PipelineRun record.
  - Polling Jenkins pipeline stage progress.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import quote

import httpx
from celery import Celery

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
        poll_pipeline_stages.apply_async(  # type: ignore[attr-defined]
            args=[run_id, job_name, build_number, build_url],
            countdown=10,
        )
        return {"run_id": run_id, "build_number": build_number}
    except Exception as exc:
        logger.error("Failed to trigger Jenkins build for run %d: %s", run_id, exc)
        if self.request.retries >= self.max_retries:
            fallback_result = "ABORTED"
            try:
                asyncio.run(_finalize_exhausted_poll(run_id, fallback_result))
            except Exception as finalize_exc:
                logger.error(
                    "Failed to finalize trigger exhaustion for run %d: %s",
                    run_id,
                    finalize_exc,
                )
            return {
                "run_id": run_id,
                "done": False,
                "error": str(exc),
                "finalized_as": fallback_result,
            }
        raise self.retry(exc=exc)


async def _trigger_jenkins(
    job_name: str,
    branch: str,
    commit_sha: str | None,
) -> tuple[int, str]:
    url_candidates = _build_trigger_url_candidates(job_name, branch)
    auth = (settings.JENKINS_USER, settings.JENKINS_TOKEN)

    params: dict = {}
    if commit_sha:
        params["GIT_COMMIT"] = commit_sha
    params["BRANCH"] = branch

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        queue_url = ""
        last_error = ""
        for url in url_candidates:
            # Try parameterized build first, then plain build for jobs that
            # don't expose buildWithParameters.
            for endpoint in ("buildWithParameters", "build"):
                trigger_url = f"{url}/{endpoint}"
                request_params = params if endpoint == "buildWithParameters" else None
                resp = await client.post(trigger_url, auth=auth, params=request_params)
                if resp.status_code in (200, 201, 202):
                    queue_url = resp.headers.get("Location", "")
                    break
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                if resp.status_code == 404:
                    continue
            if queue_url:
                break

        if not queue_url and last_error:
            raise RuntimeError(f"Jenkins trigger failed for '{job_name}' ({last_error})")

    build_number, build_url = await _resolve_queue_item(queue_url, auth)
    return build_number, build_url


def _encode_jenkins_path(*segments: str) -> str:
    cleaned = [s.strip("/") for s in segments if s and s.strip("/")]
    return "/".join(f"job/{quote(seg, safe='')}" for seg in cleaned)


def _build_trigger_url_candidates(job_name: str, branch: str) -> list[str]:
    """Return candidate Jenkins job roots from most specific to fallback."""
    candidates: list[str] = []
    normalized = job_name.strip("/")
    branch_clean = branch.strip("/")

    base = normalized
    if branch_clean and normalized.endswith(f"/{branch_clean}"):
        base = normalized[: -(len(branch_clean) + 1)]

    base_parts = [p for p in base.split("/") if p]
    normalized_parts = [p for p in normalized.split("/") if p]

    # 1) Full multibranch path: <base>/<branch>
    if base_parts and branch_clean:
        candidates.append(f"{settings.JENKINS_URL}/{_encode_jenkins_path(*base_parts, branch_clean)}")

    # 2) Repo-level fallback: drop leading org/folder from <org>/<repo>
    if len(base_parts) >= 2 and branch_clean:
        candidates.append(f"{settings.JENKINS_URL}/{_encode_jenkins_path(base_parts[-1], branch_clean)}")

    # 3) Plain job fallback without explicit branch
    if base_parts:
        candidates.append(f"{settings.JENKINS_URL}/{_encode_jenkins_path(*base_parts)}")
    if normalized_parts:
        candidates.append(f"{settings.JENKINS_URL}/{_encode_jenkins_path(*normalized_parts)}")

    # Preserve order but drop duplicates
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


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
    from app.db import get_session_factory
    from app.services.job_scheduler import on_build_started

    session_factory = get_session_factory()
    async with session_factory() as session:
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
    build_url: str | None = None,
) -> dict:
    # _sync_stages errors are handled separately from the normal "not done yet"
    # retry path. Placing `raise self.retry()` inside a try/except(Exception)
    # causes the Retry exception to be caught by that same handler, which
    # double-increments the retry counter and burns retries at 2× the expected rate.
    try:
        done = asyncio.run(_sync_stages(run_id, job_name, build_number, build_url))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error("Stage poll exhausted retries for run %d", run_id)
            fallback_result = "ABORTED" if not build_number else "FAILURE"
            try:
                asyncio.run(_finalize_exhausted_poll(run_id, fallback_result))
            except Exception as finalize_exc:
                logger.error(
                    "Failed to finalize exhausted poll for run %d: %s",
                    run_id,
                    finalize_exc,
                )
            return {
                "run_id": run_id,
                "done": False,
                "error": str(exc),
                "finalized_as": fallback_result,
            }
        raise self.retry(exc=exc, countdown=10)
    if not done:
        raise self.retry(countdown=10)
    return {"run_id": run_id, "done": True}


async def _finalize_exhausted_poll(run_id: int, fallback_result: str) -> None:
    """Fail-safe completion for runs that never receive a terminal Jenkins status."""
    from app.db import get_session_factory
    from app.pipeline_models import RunStatus
    from app.services.job_scheduler import get_run as _get_run
    from app.services.job_scheduler import on_build_completed as _on_build_completed

    session_factory = get_session_factory()
    async with session_factory() as session:
        run = await _get_run(session, run_id)
        if not run:
            return
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED):
            return
        await _on_build_completed(session, run_id, fallback_result)


async def _sync_stages(
    run_id: int,
    job_name: str,
    build_number: int,
    build_url: str | None = None,
) -> bool:
    """Fetch Jenkins Workflow Stage API and reconcile with StageExecution rows."""
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
    if build_url:
        build_root = build_url.rstrip("/")
    else:
        build_root = f"{settings.JENKINS_URL}/job/{encoded_job}/{build_number}"
    api_url = f"{build_root}/wfapi/describe"
    auth = (settings.JENKINS_USER, settings.JENKINS_TOKEN)

    from app.db import get_session_factory
    session_factory = get_session_factory()

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

        async with session_factory() as session:
            for js in jenkins_stages:
                name   = js.get("name", "")
                status = js.get("status", "")

                if status == "IN_PROGRESS":
                    await _on_ss(session, run_id, name)

                elif status in ("SUCCESS", "FAILED", "UNSTABLE"):
                    log_excerpt = None
                    try:
                        log_url = f"{build_root}/execution/node/{js.get('id', '')}/wfapi/log"
                        log_resp = await client.get(log_url, auth=auth)
                        if log_resp.status_code == 200:
                            log_excerpt = log_resp.json().get("text", "")[-1000:]
                    except Exception as exc:
                        logger.debug("Could not fetch stage log for '%s': %s", name, exc)

                    await _on_sc(
                        session, run_id, name,
                        success=(status == "SUCCESS"),
                        log_excerpt=log_excerpt,
                    )

            if build_status in ("SUCCESS", "FAILURE", "ABORTED", "UNSTABLE"):
                await _on_bc(session, run_id, build_status)
                return True

    return False
