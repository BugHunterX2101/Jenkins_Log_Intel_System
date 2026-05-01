"""
Celery background tasks — failure-analysis pipeline.
"""

import asyncio
import json
import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "jenkins_lie",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.task_serializer  = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content   = ["json"]


def process_build_failure(payload: dict) -> None:
    """Synchronous wrapper — called by FastAPI BackgroundTasks."""
    asyncio.run(_process_async(payload))


@celery_app.task(name="tasks.process_build_failure", bind=True, max_retries=3)
def process_build_failure_task(self, payload: dict) -> dict:
    try:
        return asyncio.run(_process_async(payload))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 2)


async def _process_async(payload: dict) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.services import classifier, log_fetcher, log_parser, notifier, pattern_store, root_cause

    build        = payload.get("build", {})
    # B1: Simulated payloads use "jobName"; real Jenkins webhooks use "name"
    job_name: str = (
        payload.get("name")
        or payload.get("jobName")
        or build.get("full_display_name")
        or "unknown"
    )
    build_number: int = int(build.get("number", 0))
    log_url: str  = build.get("full_url", f"{settings.JENKINS_URL}/job/{job_name}/{build_number}/")

    logger.info("Processing failure: %s #%d", job_name, build_number)

    # B2: Use embedded log content when present (simulate endpoint includes it)
    # avoids a slow Jenkins API roundtrip that fails when Jenkins isn't reachable
    embedded_log: str | None = build.get("fullLog") or build.get("log") or None
    if embedded_log:
        raw_log = embedded_log
        logger.info("Using embedded log for %s #%d (%d chars)", job_name, build_number, len(raw_log))
    else:
        raw_log = await log_fetcher.fetch_console_log(job_name, build_number)
    blocks       = log_parser.parse(raw_log)
    error_excerpt = "\n\n".join(b.full_text for b in blocks[:5]) if blocks else raw_log[-2000:]
    tags         = classifier.classify(error_excerpt or raw_log)
    primary_tag  = tags[0]

    engine       = create_async_engine(settings.DATABASE_URL, echo=False)
    Session      = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        patterns = await pattern_store.find_similar(session, error_excerpt)
        analysis = await root_cause.analyse(
            job_name=job_name, build_number=build_number,
            tags=tags, patterns=patterns,
            error_excerpt=error_excerpt, log_url=log_url,
        )

        if blocks:
            await pattern_store.upsert_pattern(
                session, failure_type=primary_tag.category,
                raw_sample=blocks[0].anchor_line,
            )

        from app.models import BuildEvent
        event = BuildEvent(
            job_name=job_name, build_number=build_number,
            failure_type=primary_tag.category, confidence=primary_tag.confidence,
            summary_text=analysis["summary_text"],
            fix_suggestions=json.dumps(analysis["fix_suggestions"]),
            severity=analysis["severity"], log_url=log_url,
            delivery_status="PENDING",
            log_truncated=len(raw_log.encode()) >= 10 * 1024 * 1024,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        event_id = event.id  # save before session closes

    delivery = await notifier.notify(
        job_name=job_name, build_number=build_number,
        summary_text=analysis["summary_text"],
        fix_suggestions=analysis["fix_suggestions"],
        severity=analysis["severity"], log_url=log_url,
    )

    logger.info("Delivery results for %s #%d: %s", job_name, build_number, delivery)

    # Update delivery_status now that notification result is known
    slack_ok = delivery.get("slack") == "OK"
    async with Session() as session:
        from app.models import BuildEvent as _BE
        evt = await session.get(_BE, event_id)
        if evt:
            evt.delivery_status = "OK" if slack_ok else "FAILED"
            await session.commit()
    return {"job": job_name, "build": build_number, "delivery": delivery}
