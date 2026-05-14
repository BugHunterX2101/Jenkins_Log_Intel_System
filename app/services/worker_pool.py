"""
Worker Pool — language-based routing and load-aware scheduling for CI worker nodes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.worker_models import (
    AssignmentStatus, Worker, WorkerAssignment, WorkerLanguage, WorkerStatus
)
from app.pipeline_models import PipelineRun

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
    idle_result = await session.execute(
        select(Worker).where(Worker.status == WorkerStatus.IDLE).order_by(Worker.load)
    )
    workers = list(idle_result.scalars().all())

    preferred = [w for w in workers if w.language == language]
    fallback   = [w for w in workers if w.language == WorkerLanguage.GENERIC]

    candidates = preferred or fallback or workers
    if not candidates:
        logger.warning("No idle workers available for run %d (language=%s)", run_id, language)
        return None

    candidates.sort(key=lambda w: w.load)
    chosen = candidates[0]

    chosen.status = WorkerStatus.BUSY
    chosen.load   = min(1.0, chosen.load + 0.5)
    chosen.last_heartbeat = datetime.now(timezone.utc)

    run_result = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run_obj = run_result.scalar_one_or_none()
    chosen.current_job = (run_obj.jenkins_job_name or run_obj.repo_url) if run_obj else f"run-{run_id}"

    assignment = WorkerAssignment(
        run_id=run_id,
        worker_id=chosen.id,
        status=AssignmentStatus.ASSIGNED,
        started_at=None,
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
    worker.load   = max(0.0, worker.load - 0.5)
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
        "capabilities": w.capabilities,
    }
