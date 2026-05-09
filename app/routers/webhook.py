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
    """Run failure processing out-of-band so webhook ACK returns immediately."""
    from app.tasks import process_build_failure
    try:
        await asyncio.to_thread(process_build_failure, payload)
    except Exception as exc:
        logger.exception("Jenkins failure processing crashed: %s", exc)


@router.post("/jenkins", summary="Receive Jenkins post-build webhook")
async def jenkins_webhook(
    request: Request,
    x_jenkins_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if not _verify_signature(body, x_jenkins_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload: dict = json.loads(body)
    build = payload.get("build", {})

    if build.get("phase") == "FINALIZED" and build.get("status") == "FAILURE":
        asyncio.create_task(_schedule_failure_processing_async(payload))

    return {"received": True}


