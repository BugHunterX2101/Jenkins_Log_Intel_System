"""
Root Cause Analyzer — generates plain-English summaries via LLM.

Provider priority:
  1. Groq  (openai-compatible)
  2. Anthropic Claude
  3. Deterministic template fallback
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.services.classifier import FailureTag
from app.services.pattern_store import PatternMatch

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {
    "infrastructure":    "P1",
    "env_issue":         "P1",
    "flaky_test":        "P2",
    "dependency_error":  "P2",
    "build_config":      "P2",
    "unknown":           "P3",
}

_SYSTEM_PROMPT = """You are a CI/CD expert. Given a Jenkins build failure context,
produce a JSON object with exactly these keys:
  "summary"         – one sentence describing the root cause
  "fix_suggestions" – list of up to 3 actionable fix steps (strings)

Respond with raw JSON only, no markdown fences."""


async def analyse(
    job_name: str,
    build_number: int,
    tags: list[FailureTag],
    patterns: list[PatternMatch],
    error_excerpt: str,
    log_url: str,
) -> dict:
    primary_tag = tags[0] if tags else FailureTag("unknown", "LOW", "", "catch-all")
    severity = _SEVERITY_MAP.get(primary_tag.category, "P2")

    pattern_context = ""
    if patterns:
        pattern_context = "\n\nHistorical similar failures:\n" + "\n".join(
            f"- [{m.failure_type}] {m.resolution_text or 'no resolution recorded'}"
            for m in patterns
        )

    user_message = (
        f"Job: {job_name} | Build: #{build_number}\n"
        f"Failure type: {primary_tag.category} (confidence: {primary_tag.confidence})\n"
        f"Matched rule: {primary_tag.matched_rule}\n\n"
        f"Error excerpt:\n{error_excerpt[:2000]}"
        f"{pattern_context}"
    )

    if settings.GROQ_API_KEY:
        result = await _call_groq(user_message, primary_tag)
        if result:
            result.update({"severity": severity, "log_url": log_url})
            return result

    if settings.ANTHROPIC_API_KEY:
        result = await _call_anthropic(user_message, primary_tag)
        if result:
            result.update({"severity": severity, "log_url": log_url})
            return result

    logger.warning("All LLM providers unavailable; using template fallback")
    return {
        "summary_text":    _fallback_summary(primary_tag),
        "fix_suggestions": _fallback_fixes(primary_tag, patterns),
        "severity":        severity,
        "log_url":         log_url,
    }


async def _call_groq(user_message: str, tag: FailureTag) -> dict | None:
    try:
        import httpx
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            "max_tokens": 512,
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.GROQ_BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw)
        return {
            "summary_text":    parsed.get("summary", _fallback_summary(tag)),
            "fix_suggestions": parsed.get("fix_suggestions", [])[:3],
        }

    except Exception as exc:
        logger.warning("Groq call failed: %s", exc)
        return None


async def _call_anthropic(user_message: str, tag: FailureTag) -> dict | None:
    try:
        import anthropic
        import asyncio

        def _sync_call():
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return message.content[0].text.strip()

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _sync_call)
        parsed = json.loads(raw)
        return {
            "summary_text":    parsed.get("summary", _fallback_summary(tag)),
            "fix_suggestions": parsed.get("fix_suggestions", [])[:3],
        }

    except Exception as exc:
        logger.warning("Anthropic call failed: %s", exc)
        return None


_SUMMARY_TEMPLATES = {
    "flaky_test":        "Build failed due to a suspected flaky or order-dependent test.",
    "env_issue":         "Build failed because a required environment variable or secret is missing.",
    "dependency_error":  "Build failed while resolving a package dependency.",
    "build_config":      "Build failed due to a Jenkinsfile or pipeline configuration error.",
    "infrastructure":    "Build failed due to an infrastructure issue (OOM, agent offline, or disk full).",
    "unknown":           "Build failed for an unclassified reason — manual log review required.",
}

_FIX_TEMPLATES: dict[str, list[str]] = {
    "flaky_test": [
        "Re-run the build to confirm flakiness.",
        "Isolate and quarantine the failing test.",
        "Check for shared state or test-ordering dependencies.",
    ],
    "env_issue": [
        "Verify all required environment variables are set in Jenkins credentials.",
        "Check the job's Bindings / Secret injection configuration.",
        "Confirm IAM / vault policies grant access to the required secrets.",
    ],
    "dependency_error": [
        "Check network connectivity to the package registry.",
        "Verify the dependency version exists and has not been yanked.",
        "Clear the dependency cache on the build agent.",
    ],
    "build_config": [
        "Validate the Jenkinsfile syntax with `jenkins-linter`.",
        "Check for recently merged pipeline changes.",
        "Review the Jenkins plugin versions for compatibility.",
    ],
    "infrastructure": [
        "Check agent disk space and memory usage.",
        "Restart the affected build agent.",
        "Escalate to platform engineering if the agent remains offline.",
    ],
    "unknown": [
        "Review the full build log at the link provided.",
        "Add the failure pattern to the classifier rule YAML.",
        "Escalate to the owning team for manual triage.",
    ],
}


def _fallback_summary(tag: FailureTag) -> str:
    return _SUMMARY_TEMPLATES.get(tag.category, _SUMMARY_TEMPLATES["unknown"])


def _fallback_fixes(tag: FailureTag, patterns: list[PatternMatch]) -> list[str]:
    fixes = _FIX_TEMPLATES.get(tag.category, _FIX_TEMPLATES["unknown"]).copy()
    for pattern in patterns[:1]:
        if pattern.resolution_text:
            fixes.insert(0, pattern.resolution_text)
    return fixes[:3]
