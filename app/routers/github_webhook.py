"""
GitHub Webhook Router

Handles real GitHub webhook payloads at TWO paths:
  - POST /webhook/github        (original internal path)
  - POST /github-webhook/       (ngrok-exposed path configured on GitHub)

Both paths call the same _handle_github_event() core function.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from app.config import settings

logger = logging.getLogger(__name__)

# Primary internal router
router = APIRouter(prefix="/webhook", tags=["webhooks"])

# Alias router — matches the ngrok-exposed URL /github-webhook/
github_alias_router = APIRouter(prefix="", tags=["webhooks"])

_GH_SECRET: str = settings.GITHUB_WEBHOOK_SECRET


def _verify_github_sig(body: bytes, sig_header: str | None) -> bool:
    """Verify HMAC-SHA256 signature from GitHub. Permissive when no secret set."""
    if not _GH_SECRET:
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        logger.warning("GitHub webhook: missing or malformed signature header")
        return False
    expected = "sha256=" + hmac.new(
        _GH_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


async def _handle_github_event(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None,
    x_github_event: str | None,
) -> dict:
    """Core handler for real GitHub webhook payloads."""
    body = await request.body()

    if not _verify_github_sig(body, x_hub_signature_256):
        logger.warning("GitHub webhook: invalid HMAC signature — rejecting")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = x_github_event or "unknown"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("GitHub webhook: malformed JSON body — %s", exc)
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    repo_obj  = payload.get("repository", {})
    repo_url  = repo_obj.get("clone_url") or repo_obj.get("html_url") or ""
    repo_name = repo_obj.get("full_name", "unknown")

    branch: str | None = None
    if event == "push":
        ref = payload.get("ref", "")
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/"):]
        else:
            # Tag push or non-branch ref — skip
            logger.info("GitHub push: non-branch ref %s — skipping", ref)
            return {"received": True, "skipped": True, "reason": f"Non-branch ref: {ref}"}

    elif event == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"received": True, "skipped": True, "reason": f"PR action '{action}' ignored"}
        branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")

    elif event == "ping":
        # GitHub sends a ping when a webhook is first configured — acknowledge it
        hook_id = payload.get("hook_id", "?")
        logger.info("GitHub webhook PING received (hook_id=%s) — webhook is live!", hook_id)
        return {"received": True, "event": "ping", "message": "Webhook is live!"}

    else:
        logger.debug("GitHub webhook: unhandled event type '%s' — ignoring", event)
        return {"received": True, "skipped": True, "reason": f"Event '{event}' not handled"}

    if not branch:
        return {"received": True, "skipped": True, "reason": "Could not resolve branch name"}

    if not repo_url:
        # Fallback: construct URL from repo full_name
        if repo_name and repo_name != "unknown":
            repo_url = f"https://github.com/{repo_name}.git"
        else:
            return {"received": True, "skipped": True, "reason": "No repository URL in payload"}

    commit_sha: str | None = (
        payload.get("after")
        or payload.get("head_commit", {}).get("id")
        or payload.get("pull_request", {}).get("head", {}).get("sha")
    )
    author: str | None = (
        payload.get("pusher", {}).get("name")
        or payload.get("sender", {}).get("login")
        or payload.get("pull_request", {}).get("user", {}).get("login")
    )
    changed_files = sorted({
        path
        for commit in payload.get("commits", []) or []
        for path in (
            commit.get("added", [])
            + commit.get("modified", [])
            + commit.get("removed", [])
        )
        if path
    })

    logger.info(
        "REAL GitHub webhook: event=%s repo=%s branch=%s author=%s commit=%s",
        event, repo_name, branch, author, (commit_sha or "")[:8]
    )

    bg.add_task(_enqueue_run, repo_url, branch, commit_sha, author, f"github-{event}", changed_files)
    return {
        "received": True,
        "real": True,
        "repo": repo_name,
        "repo_url": repo_url,
        "branch": branch,
        "author": author,
        "commit": (commit_sha or "")[:8],
        "event": event,
        "changed_files": len(changed_files),
    }


# ── Route: /webhook/github  (original path) ───────────────────────────────────
@router.post("/github", summary="Receive GitHub push/PR webhook (original path)")
async def github_webhook(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event:      str | None = Header(default=None),
) -> dict:
    return await _handle_github_event(request, bg, x_hub_signature_256, x_github_event)


# ── Route: /github-webhook/  (ngrok-exposed alias path) ───────────────────────
@github_alias_router.post("/github-webhook",  summary="Receive GitHub push/PR (ngrok alias)")
@github_alias_router.post("/github-webhook/", summary="Receive GitHub push/PR (ngrok alias with slash)")
async def github_webhook_alias(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event:      str | None = Header(default=None),
) -> dict:
    return await _handle_github_event(request, bg, x_hub_signature_256, x_github_event)


async def _enqueue_run(
    repo_url: str,
    branch: str,
    commit_sha: str | None,
    author: str | None,
    triggered_by: str,
    changed_files: list[str] | None = None,
) -> None:
    from app.db import get_session_factory
    from app.services.job_scheduler import schedule_pipeline

    session_factory = get_session_factory()
    async with session_factory() as session:
        run = await schedule_pipeline(
            session=session,
            repo_url=repo_url,
            branch=branch,
            commit_sha=commit_sha,
            author=author,
            triggered_by=triggered_by,
            changed_files=changed_files,
        )
        logger.info(
            "Enqueued PipelineRun id=%s for %s@%s (triggered_by=%s)",
            getattr(run, 'id', '?'), repo_url, branch, triggered_by
        )



