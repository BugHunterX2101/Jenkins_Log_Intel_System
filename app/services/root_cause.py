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
import re

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

_SYSTEM_PROMPT = """You are a CI/CD expert analyzing a real Jenkins build failure log.

Read the BUILD LOG EXCERPT carefully and produce VALID JSON with exactly these two keys:
  "summary"         - one sentence describing the SPECIFIC root cause found in the log.
                      You MUST mention the exact error message, command, file, or package
                      that caused the failure — not a generic category description.
  "fix_suggestions" - a JSON array of up to 3 strings. Each suggestion MUST reference
                      specific details visible in the log: exact error text, package names,
                      file paths, line numbers, or failing commands. Do NOT give generic
                      category advice that ignores the actual log content.

ALL string values MUST be enclosed in double quotes. No trailing commas.
Respond with raw JSON only — no markdown fences, no extra text."""


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
        pattern_context = "\n\nPreviously resolved similar failures:\n" + "\n".join(
            f"- {m.resolution_text}"
            for m in patterns[:2]
            if m.resolution_text
        )

    # Put the raw log excerpt FIRST so the LLM anchors to it, not the category label
    user_message = (
        f"BUILD LOG EXCERPT (analyze this):\n"
        f"{'─' * 60}\n"
        f"{error_excerpt[:2500]}\n"
        f"{'─' * 60}\n\n"
        f"Job: {job_name} | Build: #{build_number} | "
        f"Classifier hint: {primary_tag.category} (matched: {primary_tag.matched_rule})"
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
            "response_format": {"type": "json_object"},
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
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        if not raw:
            return None

        parsed = _safe_json_loads(raw)
        if parsed is None:
            return None

        summary = parsed.get("summary") or _fallback_summary(tag)
        fixes = [f for f in parsed.get("fix_suggestions", []) if isinstance(f, str)]
        return {
            "summary_text":    summary,
            "fix_suggestions": fixes[:3],
        }

    except Exception as exc:
        logger.warning("Groq call failed: %s", exc)
        return None


def _safe_json_loads(raw: str) -> dict | None:
    """Parse JSON with a lightweight repair pass for common LLM formatting errors."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 1: quote unquoted string values after known string keys
    repaired = re.sub(
        r'"(summary)"\s*:\s*([^"\[{\n][^\n,}]*)',
        lambda m: f'"{m.group(1)}": "{m.group(2).strip()}"',
        raw,
    )
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract "summary" value via regex as last resort
    summary_match = re.search(r'"summary"\s*:\s*"?([^"\n,}{]+)"?', raw)
    fixes_matches  = re.findall(r'"([^"]{10,})"', raw)
    if summary_match:
        return {
            "summary": summary_match.group(1).strip(),
            "fix_suggestions": fixes_matches[1:4] if len(fixes_matches) > 1 else [],
        }

    logger.warning("Could not parse or repair Groq JSON response: %r", raw[:200])
    return None


async def _call_anthropic(user_message: str, tag: FailureTag) -> dict | None:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        from anthropic.types import TextBlock
        text_blocks = [b for b in message.content if isinstance(b, TextBlock)]
        raw = text_blocks[0].text.strip() if text_blocks else ""
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        if not raw:
            return None
        parsed = json.loads(raw)
        summary = parsed.get("summary") or _fallback_summary(tag)
        fixes = [f for f in parsed.get("fix_suggestions", []) if isinstance(f, str)]
        return {
            "summary_text":    summary,
            "fix_suggestions": fixes[:3],
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
