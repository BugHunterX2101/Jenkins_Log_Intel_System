"""
Notification Service — Slack Block Kit + HTML email.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from app.config import settings

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "P1": "🔴",
    "P2": "🟠",
    "P3": "🟡",
}

_FAILURE_TYPE_LABEL = {
    "flaky_test":       "Flaky / Order-dependent Test",
    "env_issue":        "Missing Environment Variable / Secret",
    "dependency_error": "Package Dependency Resolution",
    "build_config":     "Jenkinsfile / Pipeline Config",
    "infrastructure":   "Infrastructure (OOM / Agent / Disk)",
    "unknown":          "Unclassified — manual review needed",
}


async def send_slack(
    job_name: str,
    build_number: int,
    summary_text: str,
    fix_suggestions: list[str],
    severity: str,
    log_url: str,
    error_excerpt: str = "",
    failure_type: str = "unknown",
    channel: str | None = None,
) -> None:
    if not settings.SLACK_BOT_TOKEN:
        logger.info("SLACK_BOT_TOKEN not configured — skipping Slack notification")
        return

    target = channel or settings.SLACK_DEFAULT_CHANNEL
    emoji = _SEVERITY_EMOJI.get(severity, "🔴")
    type_label = _FAILURE_TYPE_LABEL.get(failure_type, failure_type)

    fix_lines = "\n".join(f"{i+1}. {f}" for i, f in enumerate(fix_suggestions))

    # Slack header text max is 150 chars; truncate job_name if needed
    short_name = job_name[:60] + "…" if len(job_name) > 60 else job_name
    header_text = f"{emoji} Build Failure — {short_name} #{build_number} [{severity}]"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Job*\n`{job_name}`"},
                {"type": "mrkdwn", "text": f"*Build*\n#{build_number}"},
                {"type": "mrkdwn", "text": f"*Failure Type*\n{type_label}"},
                {"type": "mrkdwn", "text": f"*Severity*\n{severity}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"💡 *Root Cause*\n{summary_text}",
            },
        },
    ]

    if error_excerpt:
        excerpt = error_excerpt[:600].strip()
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔎 *Error Excerpt*\n```{excerpt}```",
            },
        })

    if fix_lines:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🛠️ *Suggested Fixes*\n{fix_lines}",
            },
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Build Log", "emoji": True},
                "url": log_url,
                "style": "danger",
            }
        ],
    })

    client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    try:
        await client.chat_postMessage(
            channel=target,
            blocks=blocks,
            text=f"{emoji} Build Failure — {job_name} #{build_number}: {summary_text}",
        )
        logger.info("Slack notification sent for %s #%d to %s", job_name, build_number, target)
    except SlackApiError as exc:
        error_msg = (exc.response or {}).get("error", str(exc))
        # Respect Slack rate limits
        if error_msg == "ratelimited":
            retry_after = int((exc.response or {}).get("headers", {}).get("Retry-After", 5))
            logger.warning("Slack rate-limited — retry after %ds", retry_after)
        else:
            logger.error("Slack API error for %s #%d: %s", job_name, build_number, error_msg)
        raise


async def notify(
    job_name: str,
    build_number: int,
    summary_text: str,
    fix_suggestions: list[str],
    severity: str,
    log_url: str,
    error_excerpt: str = "",
    failure_type: str = "unknown",
    email_to: str | None = None,
    slack_channel: str | None = None,
) -> dict[str, str]:
    results: dict[str, str] = {}
    tasks = [
        _run_slack(
            job_name, build_number, summary_text, fix_suggestions,
            severity, log_url, error_excerpt, failure_type, slack_channel, results,
        )
    ]
    if email_to:
        tasks.append(
            _run_email(
                job_name, build_number, summary_text, fix_suggestions,
                severity, log_url, email_to, results,
            )
        )
    await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def _run_slack(
    job_name, build_number, summary_text, fix_suggestions,
    severity, log_url, error_excerpt, failure_type, channel, results,
):
    try:
        await send_slack(
            job_name, build_number, summary_text, fix_suggestions,
            severity, log_url, error_excerpt, failure_type, channel,
        )
        results["slack"] = "OK"
    except Exception as exc:
        logger.error("Slack delivery failed for %s #%d: %s", job_name, build_number, exc)
        results["slack"] = "FAILED"


async def _run_email(
    job_name, build_number, summary_text, fix_suggestions,
    severity, log_url, to_address, results,
):
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            _send_email_sync,
            job_name, build_number, summary_text, fix_suggestions,
            severity, log_url, to_address,
        )
        results["email"] = "OK"
    except Exception as exc:
        logger.error("Email delivery failed for %s #%d: %s", job_name, build_number, exc)
        results["email"] = "FAILED"


def _send_email_sync(
    job_name: str,
    build_number: int,
    summary_text: str,
    fix_suggestions: list[str],
    severity: str,
    log_url: str,
    to_address: str,
) -> None:
    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    sender = settings.SENDER_EMAIL or f"cibot@{smtp_host}"
    fix_items = "".join(f"<li>{f}</li>" for f in fix_suggestions)
    html = (
        f"<html><body>"
        f"<h2>🔴 {job_name} #{build_number} [{severity}]</h2>"
        f"<p>{summary_text}</p>"
        f"<ol>{fix_items}</ol>"
        f"<a href='{log_url}'>View Build Log</a>"
        f"</body></html>"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{severity}] Jenkins failed — {job_name} #{build_number}"
    msg["From"]    = sender
    msg["To"]      = to_address
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if settings.SMTP_TLS:
            smtp.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(sender, [to_address], msg.as_string())
