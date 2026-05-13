"""
Jenkins Webhook Listener — POST /webhook/jenkins
"""

import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings

router = APIRouter(prefix="/webhook", tags=["webhooks"])
logger = logging.getLogger(__name__)

_WEBHOOK_SECRET: str = settings.JENKINS_WEBHOOK_SECRET


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not _WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False
    digest = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    expected_prefixed = "sha256=" + digest
    provided = signature_header.strip()
    # Accept either "sha256=<hex>" or raw hex to match different Jenkins plugins.
    return hmac.compare_digest(expected_prefixed, provided) or hmac.compare_digest(digest, provided)


async def _schedule_failure_processing_async(payload: dict) -> None:
    """Run failure processing in the same event loop — avoids asyncpg multi-loop conflict on Windows."""
    from app.tasks import _process_async
    try:
        await _process_async(payload)
    except Exception as exc:
        logger.exception("Jenkins failure processing crashed: %s", exc)


async def _handle_build_completion(payload: dict) -> None:
    """Mark the pipeline run as completed when Jenkins build finishes."""
    from app.db import get_session_factory
    from app.services.job_scheduler import on_build_completed
    from app.pipeline_models import PipelineRun
    from sqlalchemy import select
    
    build = payload.get("build", {})
    job_name = payload.get("name", "")
    build_number = build.get("number")
    result = build.get("status", "")  # SUCCESS, FAILURE, UNSTABLE, ABORTED
    
    if not job_name or not build_number or not result:
        logger.warning("Incomplete build completion payload: name=%s, number=%s, status=%s", 
                       job_name, build_number, result)
        return
    
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            # Find the PipelineRun that matches this Jenkins build
            result_query = await session.execute(
                select(PipelineRun).where(
                    PipelineRun.jenkins_job_name == job_name,
                    PipelineRun.jenkins_build_number == build_number,
                )
            )
            run = result_query.scalar_one_or_none()
            
            if not run:
                logger.warning(
                    "No PipelineRun found for job=%s, build=%s",
                    job_name, build_number
                )
                return
            
            # Mark the run as completed with the Jenkins result
            await on_build_completed(session, run_id=run.id, result=result)
            await session.commit()
            logger.info(
                "Marked run %d as %s (Jenkins job=%s #%s)",
                run.id, result, job_name, build_number
            )
    except Exception as exc:
        logger.exception(
            "Failed to handle build completion for job=%s, build=%s: %s",
            job_name, build_number, exc
        )


@router.post("/jenkins", summary="Receive Jenkins post-build webhook")
async def jenkins_webhook(
    request: Request,
    x_jenkins_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if not _verify_signature(body, x_jenkins_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: dict = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Malformed JSON payload: {exc}") from exc
    build = payload.get("build", {})

    # Handle all FINALIZED builds (SUCCESS, FAILURE, ABORTED, UNSTABLE)
    if build.get("phase") == "FINALIZED":
        # Always mark the run as completed
        asyncio.create_task(_handle_build_completion(payload))
        
        # For failures, also trigger failure analysis and notifications
        if build.get("status") == "FAILURE":
            asyncio.create_task(_schedule_failure_processing_async(payload))

    return {"received": True}


