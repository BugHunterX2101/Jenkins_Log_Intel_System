"""
Jenkins Webhook Listener — POST /webhook/jenkins
"""

import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from app.config import settings

router = APIRouter(prefix="/webhook", tags=["webhooks"])

_WEBHOOK_SECRET: str = settings.JENKINS_WEBHOOK_SECRET


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not _WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        _WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/jenkins", summary="Receive Jenkins post-build webhook")
async def jenkins_webhook(
    request: Request,
    bg: BackgroundTasks,
    x_jenkins_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if not _verify_signature(body, x_jenkins_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload: dict = json.loads(body)
    build = payload.get("build", {})

    if build.get("phase") == "FINALIZED" and build.get("status") == "FAILURE":
        from app.tasks import process_build_failure
        bg.add_task(process_build_failure, payload)

    return {"received": True}
