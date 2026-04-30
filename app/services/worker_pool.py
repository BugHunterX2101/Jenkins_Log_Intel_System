"""
Worker Pool — simulates 4 CI worker nodes with language-based routing,
load-aware scheduling, and realistic randomised execution.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.worker_models import (
    AssignmentStatus, Worker, WorkerAssignment, WorkerLanguage, WorkerStatus
)
from app.pipeline_models import PipelineRun, RunStatus, StageExecution, StageStatus

logger = logging.getLogger(__name__)

_LANG_SIGNALS: dict[WorkerLanguage, list[str]] = {
    WorkerLanguage.PYTHON: ["python", "pytest", "pip", "django", "flask", "fastapi", ".py"],
    WorkerLanguage.NODE:   ["node", "npm", "yarn", "jest", "react", "next", ".js", ".ts"],
    WorkerLanguage.JAVA:   ["java", "maven", "gradle", "spring", "kotlin", ".java"],
    WorkerLanguage.GO:     ["go", "golang", "gotest", ".go"],
    WorkerLanguage.RUBY:   ["ruby", "rails", "rspec", "bundler", ".rb"],
}

_STAGE_LANG_HINTS: dict[WorkerLanguage, list[str]] = {
    WorkerLanguage.PYTHON: ["pytest", "pip install", "python", "coverage", "mypy", "ruff"],
    WorkerLanguage.NODE:   ["npm", "yarn", "jest", "webpack", "eslint", "next build"],
    WorkerLanguage.JAVA:   ["maven", "gradle", "mvn", "java", "spring"],
    WorkerLanguage.GO:     ["go test", "go build", "golangci"],
    WorkerLanguage.RUBY:   ["bundle", "rspec", "rails"],
}

_STAGE_DURATIONS: dict[str, tuple[int, int]] = {
    "checkout":    (2,  5),
    "install":     (8, 25),
    "lint":        (4, 12),
    "test":        (10, 40),
    "build":       (8, 30),
    "docker":      (15, 45),
    "push":        (5, 20),
    "deploy":      (6, 18),
    "scan":        (5, 15),
    "package":     (7, 22),
    "coverage":    (5, 18),
    "default":     (4, 15),
}

_FAILURE_PROB = 0.10
_FLAKE_PROB   = 0.05

WORKER_SEED = [
    {"name": "worker-python-1", "language": WorkerLanguage.PYTHON,
     "capabilities": '["pytest","pip","docker","coverage"]'},
    {"name": "worker-python-2", "language": WorkerLanguage.PYTHON,
     "capabilities": '["pytest","pip","mypy","ruff"]'},
    {"name": "worker-node-1",   "language": WorkerLanguage.NODE,
     "capabilities": '["npm","jest","webpack","docker"]'},
    {"name": "worker-java-1",   "language": WorkerLanguage.JAVA,
     "capabilities": '["maven","gradle","docker","sonar"]'},
]


def detect_language(repo_url: str, stage_names: list[str]) -> WorkerLanguage:
    text = (repo_url + " " + " ".join(stage_names)).lower()
    scores: dict[WorkerLanguage, int] = {lang: 0 for lang in WorkerLanguage}

    for lang, signals in _LANG_SIGNALS.items():
        for signal in signals:
            if signal in text:
                scores[lang] += 2

    for lang, hints in _STAGE_LANG_HINTS.items():
        for hint in hints:
            if any(hint in s.lower() for s in stage_names):
                scores[lang] += 3

    best_lang = max(scores, key=lambda l: scores[l])
    if scores[best_lang] == 0:
        return WorkerLanguage.GENERIC
    return best_lang


async def seed_workers(session: AsyncSession) -> None:
    result = await session.execute(select(Worker))
    if result.scalars().first():
        return

    for spec in WORKER_SEED:
        session.add(Worker(**spec, status=WorkerStatus.IDLE, load=0.0))

    await session.commit()
    logger.info("Seeded %d workers", len(WORKER_SEED))


async def assign_worker(
    session: AsyncSession,
    run_id: int,
    language: WorkerLanguage,
) -> Optional[Worker]:
    result = await session.execute(
        select(Worker).where(Worker.status != WorkerStatus.OFFLINE)
    )
    workers = list(result.scalars().all())

    preferred = [w for w in workers if w.language == language and w.status == WorkerStatus.IDLE]
    fallback   = [w for w in workers if w.language == WorkerLanguage.GENERIC and w.status == WorkerStatus.IDLE]
    any_idle   = [w for w in workers if w.status == WorkerStatus.IDLE]

    candidates = preferred or fallback or any_idle
    if not candidates:
        logger.warning("No idle workers available for run %d (language=%s)", run_id, language)
        return None

    candidates.sort(key=lambda w: w.load + random.uniform(0, 0.1))
    chosen = candidates[0]

    chosen.status = WorkerStatus.BUSY
    chosen.load   = min(1.0, chosen.load + random.uniform(0.4, 0.7))
    chosen.last_heartbeat = datetime.now(timezone.utc)

    # Fetch the run's job name to surface in the worker card
    run_result = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run_obj = run_result.scalar_one_or_none()
    chosen.current_job = run_obj.jenkins_job_name if run_obj else None

    assignment = WorkerAssignment(
        run_id=run_id,
        worker_id=chosen.id,
        status=AssignmentStatus.ASSIGNED,
        started_at=datetime.now(timezone.utc),  # B3: ensures duration_s is set on release
    )
    session.add(assignment)
    await session.commit()
    await session.refresh(chosen)

    logger.info("Assigned worker %s (load=%.2f) to run %d", chosen.name, chosen.load, run_id)
    return chosen


async def release_worker(
    session: AsyncSession,
    worker_id: int,
    run_id: int,
    success: bool,
) -> None:
    result = await session.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        return

    worker.status = WorkerStatus.IDLE
    worker.load   = max(0.0, worker.load - random.uniform(0.3, 0.6))
    worker.jobs_run += 1
    worker.current_job = None
    worker.last_heartbeat = datetime.now(timezone.utc)

    aresult = await session.execute(
        select(WorkerAssignment).where(
            WorkerAssignment.run_id == run_id,
            WorkerAssignment.worker_id == worker_id,
        )
    )
    assignment = aresult.scalar_one_or_none()
    if assignment:
        now = datetime.now(timezone.utc)
        assignment.status       = AssignmentStatus.DONE if success else AssignmentStatus.FAILED
        assignment.completed_at = now
        assignment.result       = "SUCCESS" if success else "FAILURE"
        if assignment.started_at:
            assignment.duration_s = int((now - assignment.started_at).total_seconds())

    await session.commit()


def _stage_duration(stage_name: str) -> float:
    key = stage_name.lower()
    for pattern, (lo, hi) in _STAGE_DURATIONS.items():
        if pattern in key:
            return random.uniform(lo, hi)
    return random.uniform(*_STAGE_DURATIONS["default"])


def _stage_fails(stage_name: str) -> tuple[bool, str]:
    r = random.random()
    if "test" in stage_name.lower() and r < _FLAKE_PROB:
        return True, "flaky_test"
    if r < _FAILURE_PROB:
        reasons = ["env_issue", "dependency_error", "infrastructure", "build_config"]
        return True, random.choice(reasons)
    return False, ""


async def simulate_execution(
    run_id: int,
    worker_id: int,
    stage_names: list[str],
    db_url: str,
) -> bool:
    # These are imported at call-time to avoid circular imports at module load.
    # They are also assigned to module-level names (below) so test code can
    # patch them as patch("app.services.worker_pool.on_stage_started", ...).
    from app.services.job_scheduler import (
        on_stage_started as _on_stage_started,
        on_stage_completed as _on_stage_completed,
        on_build_completed as _on_build_completed,
        get_run as _get_run,
    )

    # Use module-level aliases if they've been patched by tests.
    # Use `or` so that a module-level None falls back to the imported function.
    import app.services.worker_pool as _wpm
    _on_ss  = getattr(_wpm, "on_stage_started",  None) or _on_stage_started
    _on_sc  = getattr(_wpm, "on_stage_completed", None) or _on_stage_completed
    _on_bc  = getattr(_wpm, "on_build_completed", None) or _on_build_completed
    _gr     = getattr(_wpm, "get_run",            None) or _get_run

    engine  = create_async_engine(db_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # FIX: When no stages were parsed from Jenkinsfile, we fall back to a
    # synthetic list. But the DB has no StageExecution rows for these names,
    # so on_stage_started/completed would silently no-op (stage query returns None).
    # Fix: create the missing StageExecution rows before executing if needed.
    if not stage_names:
        stage_names = ["Checkout", "Build", "Test", "Deploy"]
        async with Session() as session:
            run = await _gr(session, run_id)
            if run is not None and not run.stages:
                from app.pipeline_models import StageExecution, StageStatus
                for idx, name in enumerate(stage_names):
                    session.add(StageExecution(
                        run_id=run_id, order=idx, name=name,
                        status=StageStatus.PENDING,
                    ))
                # Also store the stage names on the run so the dashboard shows them
                run.stage_names_csv = ",".join(stage_names)
                await session.commit()

    overall_success = True

    for stage_name in stage_names:
        duration = _stage_duration(stage_name)
        failed, reason = _stage_fails(stage_name)

        async with Session() as session:
            await _on_ss(session, run_id, stage_name)

        logger.info("Worker %d | Run %d | Stage '%s' started (%.1fs simulated)",
                    worker_id, run_id, stage_name, duration)

        await asyncio.sleep(min(duration, 3))

        if failed:
            overall_success = False
            log_excerpt = _fake_log(stage_name, reason)
            async with Session() as session:
                await _on_sc(session, run_id, stage_name,
                             success=False, log_excerpt=log_excerpt)
            logger.warning("Worker %d | Run %d | Stage '%s' FAILED (%s)",
                           worker_id, run_id, stage_name, reason)
            break

        async with Session() as session:
            await _on_sc(session, run_id, stage_name,
                         success=True, log_excerpt=f"Stage '{stage_name}' completed OK.")

    result_str = "SUCCESS" if overall_success else "FAILURE"
    async with Session() as session:
        await _on_bc(session, run_id, result_str)

    async with Session() as session:
        await release_worker(session, worker_id, run_id, overall_success)

    await engine.dispose()
    return overall_success


def _fake_log(stage_name: str, reason: str) -> str:
    templates = {
        "flaky_test":        f"AssertionError: expected 200 got 500 in {stage_name}\n  → Suspected flaky test. Re-run to confirm.",
        "env_issue":         f"Error: Environment variable 'SECRET_KEY' not found\n  at {stage_name}/setup.sh:12",
        "dependency_error":  f"ERROR: Could not resolve dependency 'requests==9.9.9'\n  during {stage_name}",
        "infrastructure":    f"java.lang.OutOfMemoryError: GC overhead limit exceeded\n  during {stage_name}",
        "build_config":      f"WorkflowScript: No such DSL method '{stage_name}' found",
    }
    return templates.get(reason, f"Unknown error during {stage_name}")


def serialise_worker(w: Worker) -> dict:
    return {
        "id":       w.id,
        "name":     w.name,
        "language": w.language.value,
        "status":   w.status.value,
        "load":     round(w.load, 2),
        "jobs_run": w.jobs_run,
        "current_job": w.current_job,
        "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
    }


# Module-level stubs for job_scheduler callables used inside simulate_execution.
# Declaring them here (as None placeholders) means unittest.mock.patch() can
# find and replace them by name:
#   patch("app.services.worker_pool.on_stage_started", new_callable=AsyncMock)
# Without these declarations, patch() raises AttributeError because the names
# don't exist at module scope until simulate_execution is first called.
on_stage_started  = None   # populated on first simulate_execution call
on_stage_completed = None  # populated on first simulate_execution call
on_build_completed = None  # populated on first simulate_execution call
get_run           = None   # populated on first simulate_execution call
