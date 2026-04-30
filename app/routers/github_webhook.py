"""
GitHub Webhook Router — POST /webhook/github
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import string
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

_GH_SECRET: str = settings.GITHUB_WEBHOOK_SECRET


def _verify_github_sig(body: bytes, sig_header: str | None) -> bool:
    if not _GH_SECRET:
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    # hmac.new(key, msg, digestmod) is the standard Python 3 HMAC constructor alias
    expected = "sha256=" + hmac.new(
        _GH_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


@router.post("/github", summary="Receive GitHub push/PR webhook")
async def github_webhook(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event:      str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if not _verify_github_sig(body, x_hub_signature_256):
        logger.warning("GitHub webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = x_github_event or "unknown"
    payload = json.loads(body)

    repo_url  = payload.get("repository", {}).get("clone_url", "")
    repo_name = payload.get("repository", {}).get("full_name", "unknown")

    branch = None
    if event == "push":
        ref = payload.get("ref", "")
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/"):]
    elif event == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"received": True, "skipped": True, "reason": f"PR action '{action}' ignored"}
        branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")

    if not branch or not repo_url:
        return {"received": True, "skipped": True, "reason": "No branch or repo_url resolved"}

    commit_sha = (
        payload.get("after") or
        payload.get("pull_request", {}).get("head", {}).get("sha")
    )
    author = (
        payload.get("pusher", {}).get("name") or
        payload.get("pull_request", {}).get("user", {}).get("login")
    )

    logger.info("GitHub webhook: %s %s@%s (commit=%s)", event, repo_name, branch, commit_sha)

    bg.add_task(_enqueue_run, repo_url, branch, commit_sha, author, f"github-{event}")
    return {"received": True, "repo": repo_name, "branch": branch, "event": event}


async def _enqueue_run(
    repo_url: str,
    branch: str,
    commit_sha: str | None,
    author: str | None,
    triggered_by: str,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.services.job_scheduler import schedule_pipeline

    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        await schedule_pipeline(
            session=session,
            repo_url=repo_url,
            branch=branch,
            commit_sha=commit_sha,
            author=author,
            triggered_by=triggered_by,
        )

    await engine.dispose()


_DEMO_REPOS = [
    ("https://github.com/acme/auth-service",    "python"),
    ("https://github.com/acme/api-gateway",     "node"),
    ("https://github.com/acme/payment-service", "java"),
    ("https://github.com/acme/data-pipeline",   "python"),
    ("https://github.com/acme/frontend-app",    "node"),
    ("https://github.com/acme/billing-svc",     "java"),
]

class SimulateRequest(BaseModel):
    repo_url:   Optional[str] = None
    branch:     Optional[str] = None
    author:     Optional[str] = None
    count:      int           = 1


@router.post("/github/simulate", summary="Inject a simulated GitHub push event")
async def simulate_github_push(body: SimulateRequest, bg: BackgroundTasks) -> dict:
    injected = []
    for _ in range(max(1, min(body.count, 20))):
        repo_url, lang = (
            (body.repo_url, "unknown") if body.repo_url
            else random.choice(_DEMO_REPOS)
        )
        branch     = body.branch or random.choice(["main", "develop", f"feature/{_rand_str(6)}"])
        author     = body.author or random.choice(["alice", "bob", "carol", "dave", "eve"])
        commit_sha = _rand_hex(40)

        bg.add_task(
            _enqueue_run, repo_url, branch, commit_sha, author,
            "github-push-simulated"
        )
        injected.append({"repo_url": repo_url, "branch": branch, "author": author, "commit_sha": commit_sha})

    return {
        "simulated": len(injected),
        "jobs": injected,
        "message": f"Injected {len(injected)} job(s) into the queue",
    }


def _rand_str(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))

def _rand_hex(n: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=n))
