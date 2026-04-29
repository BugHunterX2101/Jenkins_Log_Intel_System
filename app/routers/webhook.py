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


@router.post("/jenkins/simulate", summary="Simulate Jenkins build failure for testing")
async def simulate_jenkins_failure(bg: BackgroundTasks) -> dict:
    """Simulate a Jenkins build failure to test the autonomous failure analysis pipeline."""
    from app.tasks import process_build_failure
    
    # Create a realistic failure payload
    payload = {
        "build": {
            "number": 12847,
            "phase": "FINALIZED",
            "status": "FAILURE",
            "url": "http://localhost:8080/job/backend-tests/12847/",
            "log": "Error in test_authentication.py:45: AssertionError - auth token validation failed",
            "fullLog": """
            [INFO] Starting tests...
            [INFO] Running test_authentication.py:45
            [ERROR] AssertionError: Expected 'VALID' but got 'INVALID'
            [ERROR] Test suite failed - 1 failure, 1 skipped
            [ERROR] Build FAILURE
            """,
            "timestamp": 1719669735000,
            "result": "FAILURE",
        },
        "jobName": "backend-tests",
        "buildNumber": 12847,
        "repositoryUrl": "https://github.com/jenkins/jenkins-blue-ocean",
    }
    
    bg.add_task(process_build_failure, payload)
    
    return {
        "simulated": True,
        "job_name": "backend-tests",
        "build_number": 12847,
        "message": "Simulated Jenkins build failure has been injected into the pipeline",
        "status": "Processing - check /ui/queue for status updates"
    }
