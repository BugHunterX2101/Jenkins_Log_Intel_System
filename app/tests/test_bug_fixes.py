"""
Regression tests covering every bug found and fixed during the audit.

Bug inventory:
  1. aiohttp missing from dependencies (import-time crash in notifier.py)
  2. test_webhook unmocked background task → real HTTP calls to jenkins.test
  3. schedule_pipeline: Celery dispatch not guarded → exception if broker absent
  4. _sync_stages: httpx client used after its context-manager closed it
  5. on_build_completed: UNSTABLE mapped to ABORTED instead of FAILED
  6. get_dashboard_snapshot / get_run: lazy-loaded run.stages raises MissingGreenlet
  7. simulate_execution: fallback stage names have no StageExecution DB rows
  8. Scheduler race condition: same QUEUED run dispatched twice by concurrent ticks
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── Bug 1: aiohttp must be importable (dependency was missing) ─────────────────

def test_aiohttp_importable():
    """aiohttp is required by slack-sdk async client; must be installed."""
    import aiohttp  # should not raise
    assert aiohttp is not None


def test_notifier_importable():
    """notifier.py imports AsyncWebClient which needs aiohttp."""
    from app.services import notifier  # should not raise
    assert notifier is not None


# ── Bug 2: webhook background task must be mockable ───────────────────────────

def test_webhook_failure_event_does_not_make_network_calls(client):
    """
    POST /webhook/jenkins with a FAILURE event must return 200 immediately.
    The background task (process_build_failure) must NOT make real HTTP calls
    to Jenkins; it should be intercepted at the task level.
    """
    import json
    payload = {
        "name": "svc",
        "build": {"phase": "FINALIZED", "status": "FAILURE",
                  "number": 1, "full_url": "http://jenkins.test/job/svc/1/"}
    }
    with patch("app.tasks.process_build_failure") as mock_fn:
        resp = client.post(
            "/webhook/jenkins",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["received"] is True
    # The background task function must have been called once
    mock_fn.assert_called_once_with(payload)


# ── Bug 3: schedule_pipeline Celery dispatch guard ────────────────────────────

@pytest.mark.asyncio
async def test_schedule_pipeline_celery_failure_does_not_propagate():
    """
    If the Celery broker is unavailable, schedule_pipeline must still return
    the PipelineRun (it should only log a warning, not raise).
    """
    from app.services.job_scheduler import schedule_pipeline
    from app.pipeline_models import RunStatus

    # Mock the DB session
    mock_session = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = 42
    mock_run.status = RunStatus.QUEUED
    mock_run.stage_names = []

    with patch("app.services.job_scheduler.get_pipeline_stages", return_value=[]), \
         patch("app.services.job_scheduler._derive_job_name", return_value="org/repo/main"), \
         patch.object(mock_session, "flush", new_callable=AsyncMock), \
         patch.object(mock_session, "commit", new_callable=AsyncMock), \
         patch.object(mock_session, "refresh", new_callable=AsyncMock), \
         patch.object(mock_session, "add"), \
         patch("app.pipeline_tasks.trigger_jenkins_build") as mock_task:

        # Simulate the Celery task raising (broker unavailable)
        mock_task.delay.side_effect = Exception("Connection refused")

        # Patch PipelineRun constructor to return our mock
        with patch("app.services.job_scheduler.PipelineRun", return_value=mock_run):
            # Should NOT raise even though Celery fails
            result = await schedule_pipeline(
                session=mock_session,
                repo_url="https://github.com/acme/svc",
                branch="main",
            )
        # The run is returned regardless of Celery failure
        assert result is mock_run


# ── Bug 4: _sync_stages closed httpx client ───────────────────────────────────

@pytest.mark.asyncio
async def test_sync_stages_uses_single_open_client():
    """
    _sync_stages must keep the httpx.AsyncClient open while fetching stage logs.
    The bug was: client closed after the first 'async with httpx.AsyncClient'
    block, then used again inside the DB session block for log fetches.
    We verify that only ONE AsyncClient is created for the whole function.
    """
    import app.pipeline_tasks as pt

    wfapi_response = {
        "status": "SUCCESS",
        "stages": [
            {"name": "Build", "status": "SUCCESS", "id": "10"},
        ]
    }

    client_instances = []

    class TrackedClient:
        """Records open/close calls to detect premature closure."""
        def __init__(self, **kwargs):   # accept timeout= and any other kwargs
            self._closed = False
            client_instances.append(self)

        async def get(self, url, **kwargs):
            assert not self._closed, "Client.get() called after client was closed!"
            mock_resp = MagicMock()
            if "wfapi/describe" in url:
                mock_resp.status_code = 200
                mock_resp.json.return_value = wfapi_response
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"text": "build log here"}
            return mock_resp

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self._closed = True

    with patch("app.pipeline_tasks.httpx.AsyncClient", TrackedClient), \
         patch("app.db.get_session_factory") as mock_sf:

        mock_session = AsyncMock()
        mock_sf.return_value.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.pipeline_tasks.on_stage_started", new_callable=AsyncMock), \
             patch("app.pipeline_tasks.on_stage_completed", new_callable=AsyncMock), \
             patch("app.pipeline_tasks.on_build_completed", new_callable=AsyncMock), \
             patch("app.pipeline_tasks.get_run", new_callable=AsyncMock):
            await pt._sync_stages(run_id=1, job_name="org/repo/main", build_number=5)

    # Exactly one client should have been created
    assert len(client_instances) == 1


# ── Bug 5: UNSTABLE build result must map to FAILED ──────────────────────────

@pytest.mark.asyncio
async def test_on_build_completed_unstable_maps_to_failed():
    """
    Jenkins UNSTABLE builds (tests pass but with issues) should appear as
    FAILED in the dashboard, not ABORTED. The original code used a catch-all
    'else: ABORTED' that swallowed UNSTABLE into the wrong bucket.
    """
    from app.services.job_scheduler import on_build_completed
    from app.pipeline_models import RunStatus, StageStatus

    mock_run = MagicMock()
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.stages = []

    mock_session = AsyncMock()

    with patch("app.services.job_scheduler.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch.object(mock_session, "commit", new_callable=AsyncMock):
        await on_build_completed(mock_session, run_id=1, result="UNSTABLE")

    assert mock_run.status == RunStatus.FAILED, (
        f"UNSTABLE should map to FAILED, got {mock_run.status}"
    )


@pytest.mark.asyncio
async def test_on_build_completed_aborted_maps_to_aborted():
    """ABORTED builds must still map to RunStatus.ABORTED (not FAILED)."""
    from app.services.job_scheduler import on_build_completed
    from app.pipeline_models import RunStatus

    mock_run = MagicMock()
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.stages = []

    mock_session = AsyncMock()
    with patch("app.services.job_scheduler.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch.object(mock_session, "commit", new_callable=AsyncMock):
        await on_build_completed(mock_session, run_id=1, result="ABORTED")

    assert mock_run.status == RunStatus.ABORTED


@pytest.mark.asyncio
async def test_on_build_completed_success_maps_to_completed():
    """SUCCESS builds must map to RunStatus.COMPLETED."""
    from app.services.job_scheduler import on_build_completed
    from app.pipeline_models import RunStatus

    mock_run = MagicMock()
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.stages = []

    mock_session = AsyncMock()
    with patch("app.services.job_scheduler.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch.object(mock_session, "commit", new_callable=AsyncMock):
        await on_build_completed(mock_session, run_id=1, result="SUCCESS")

    assert mock_run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_on_build_completed_failure_maps_to_failed():
    """FAILURE builds must map to RunStatus.FAILED."""
    from app.services.job_scheduler import on_build_completed
    from app.pipeline_models import RunStatus

    mock_run = MagicMock()
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.stages = []

    mock_session = AsyncMock()
    with patch("app.services.job_scheduler.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch.object(mock_session, "commit", new_callable=AsyncMock):
        await on_build_completed(mock_session, run_id=1, result="FAILURE")

    assert mock_run.status == RunStatus.FAILED


# ── Bug 5b: all four Jenkins terminal states handled correctly ─────────────────

@pytest.mark.parametrize("jenkins_result,expected_status", [
    ("SUCCESS",  "COMPLETED"),
    ("FAILURE",  "FAILED"),
    ("ABORTED",  "ABORTED"),
    ("UNSTABLE", "FAILED"),   # was incorrectly ABORTED before fix
])
@pytest.mark.asyncio
async def test_build_result_mapping_parametrized(jenkins_result, expected_status):
    from app.services.job_scheduler import on_build_completed

    mock_run = MagicMock()
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.stages = []
    mock_session = AsyncMock()

    with patch("app.services.job_scheduler.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch.object(mock_session, "commit", new_callable=AsyncMock):
        await on_build_completed(mock_session, run_id=1, result=jenkins_result)

    assert mock_run.status.value == expected_status, (
        f"Jenkins '{jenkins_result}' should map to '{expected_status}', "
        f"got '{mock_run.status.value}'"
    )


# ── Bug 6: get_dashboard_snapshot / get_run must use selectinload ─────────────

def test_get_dashboard_snapshot_uses_selectinload():
    """
    get_dashboard_snapshot() must use selectinload(PipelineRun.stages) to avoid
    MissingGreenlet errors from lazy-loading the stages relationship in async
    SQLAlchemy. Verify the query is built with the correct eager-load option.
    """
    import inspect
    from sqlalchemy.orm import selectinload
    from app.services import job_scheduler
    import app.pipeline_models as pm

    src = inspect.getsource(job_scheduler.get_dashboard_snapshot)
    assert "selectinload" in src, (
        "get_dashboard_snapshot must use selectinload(PipelineRun.stages) "
        "to prevent async lazy-load MissingGreenlet errors"
    )


def test_get_run_uses_selectinload():
    """
    get_run() must use selectinload(PipelineRun.stages) so callers can access
    run.stages without triggering an async lazy load.
    """
    import inspect
    from app.services import job_scheduler

    src = inspect.getsource(job_scheduler.get_run)
    assert "selectinload" in src, (
        "get_run must use selectinload(PipelineRun.stages) "
        "to prevent async lazy-load MissingGreenlet errors"
    )


# ── Bug 7: simulate_execution fallback stages need DB rows ───────────────────

@pytest.mark.asyncio
async def test_simulate_execution_creates_stage_rows_for_fallback():
    """
    When stage_names is empty, simulate_execution falls back to
    ['Checkout','Build','Test','Deploy']. These stages have no StageExecution
    rows in the DB. The fix: create the rows before simulating.

    We verify that StageExecution objects are added to the session when
    stage_names is empty and run.stages is also empty.
    """
    from app.services.worker_pool import simulate_execution
    from app.pipeline_models import StageExecution, StageStatus, RunStatus

    added_objects = []

    mock_run = MagicMock()
    mock_run.stages = []  # no existing stages
    mock_run.stage_names_csv = None

    mock_session = AsyncMock()
    mock_session.add = lambda obj: added_objects.append(obj)

    with patch("app.services.worker_pool.create_async_engine", return_value=AsyncMock()), \
         patch("app.services.worker_pool.sessionmaker") as mock_sf, \
         patch("app.services.worker_pool.on_stage_started", new_callable=AsyncMock), \
         patch("app.services.worker_pool.on_stage_completed", new_callable=AsyncMock), \
         patch("app.services.worker_pool.on_build_completed", new_callable=AsyncMock), \
         patch("app.services.worker_pool.release_worker", new_callable=AsyncMock), \
         patch("app.services.worker_pool.get_run", new_callable=AsyncMock, return_value=mock_run):

        # Make sessionmaker return a context manager that yields mock_session
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value.return_value = ctx

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await simulate_execution(
                run_id=1,
                worker_id=1,
                stage_names=[],   # empty → triggers the fallback path
                db_url="postgresql+asyncpg://x:x@localhost/x",
            )

    # StageExecution objects should have been added for the fallback stages
    stage_objects = [o for o in added_objects if isinstance(o, StageExecution)]
    assert len(stage_objects) == 4, (
        f"Expected 4 fallback StageExecution rows to be created, got {len(stage_objects)}"
    )
    stage_names_created = [s.name for s in stage_objects]
    assert stage_names_created == ["Checkout", "Build", "Test", "Deploy"]


# ── Bug 8: Scheduler race condition ───────────────────────────────────────────

def test_scheduler_uses_atomic_update_to_claim_runs():
    """
    The scheduler tick must use an atomic UPDATE ... WHERE status=QUEUED to
    claim runs, preventing two concurrent ticks from dispatching the same run
    to two different workers.

    We inspect the scheduler source to confirm:
    1. An UPDATE statement is used (not just SELECT + Python-side set).
    2. The WHERE clause includes status == QUEUED as an atomic guard.
    3. rowcount == 0 causes the run to be skipped.
    """
    import inspect
    from app import scheduler

    src = inspect.getsource(scheduler._scheduler_tick_async)

    assert "update(PipelineRun)" in src, (
        "Scheduler must use SQLAlchemy update() for atomic run claiming"
    )
    assert "RunStatus.QUEUED" in src, (
        "The UPDATE must include WHERE status=QUEUED as an atomic guard"
    )
    assert "rowcount" in src, (
        "Scheduler must check rowcount to detect concurrent claim conflicts"
    )


def test_scheduler_reverts_run_when_no_worker_available():
    """
    If a run is claimed (set to IN_PROGRESS) but no worker is available,
    the scheduler must revert the run back to QUEUED so the next tick retries.
    """
    import inspect
    from app import scheduler

    src = inspect.getsource(scheduler._scheduler_tick_async)

    # The revert path: set back to QUEUED when no worker found
    assert "RunStatus.QUEUED" in src
    # There should be a second update (the revert) after the first (the claim)
    assert src.count("update(PipelineRun)") >= 2, (
        "Scheduler needs two UPDATE statements: one to claim, one to revert on no-worker"
    )


# ── Integration: all status mappings reachable from _sync_stages ─────────────

def test_sync_stages_calls_on_build_completed_for_all_terminal_states():
    """
    _sync_stages must call on_build_completed for SUCCESS, FAILURE, ABORTED,
    and UNSTABLE. Verify the terminal-state set in the source.
    """
    import inspect
    from app import pipeline_tasks

    src = inspect.getsource(pipeline_tasks._sync_stages)

    for state in ("SUCCESS", "FAILURE", "ABORTED", "UNSTABLE"):
        assert state in src, (
            f"_sync_stages must handle terminal state '{state}'"
        )
