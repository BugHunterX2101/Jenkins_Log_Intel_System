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


async def send_slack(job_name, build_number, summary_text, fix_suggestions, severity, log_url, channel=None):
    target    = channel or settings.SLACK_DEFAULT_CHANNEL
    fix_lines = "\n".join(f"• {f}" for f in fix_suggestions)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🔴 Build Failure — {job_name} #{build_number} [{severity}]"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{summary_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Fix Suggestions*\n{fix_lines}"}},
        {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "View Build Log"}, "url": log_url}]},
    ]
    client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    try:
        await client.chat_postMessage(channel=target, blocks=blocks, text=summary_text)
    except SlackApiError as exc:
        logger.error("Slack failed: %s", exc.response["error"])
        raise


async def notify(job_name, build_number, summary_text, fix_suggestions, severity, log_url,
                 email_to=None, slack_channel=None) -> dict[str, str]:
    results: dict[str, str] = {}
    tasks = [_run_slack(job_name, build_number, summary_text, fix_suggestions, severity, log_url, slack_channel, results)]
    if email_to:
        tasks.append(_run_email(job_name, build_number, summary_text, fix_suggestions, severity, log_url, email_to, results))
    await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def _run_slack(job_name, build_number, summary_text, fix_suggestions, severity, log_url, channel, results):
    try:
        await send_slack(job_name, build_number, summary_text, fix_suggestions, severity, log_url, channel)
        results["slack"] = "OK"
    except Exception as exc:
        logger.error("Slack delivery failed: %s", exc)
        results["slack"] = "FAILED"


async def _run_email(job_name, build_number, summary_text, fix_suggestions, severity, log_url, to_address, results):
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _send_email_sync, job_name, build_number, summary_text, fix_suggestions, severity, log_url, to_address)
        results["email"] = "OK"
    except Exception as exc:
        logger.error("Email delivery failed: %s", exc)
        results["email"] = "FAILED"


def _send_email_sync(job_name, build_number, summary_text, fix_suggestions, severity, log_url, to_address, smtp_host="localhost", smtp_port=25):
    fix_items = "".join(f"<li>{f}</li>" for f in fix_suggestions)
    html = f"<html><body><h2>🔴 {job_name} #{build_number} [{severity}]</h2><p>{summary_text}</p><ol>{fix_items}</ol><a href='{log_url}'>View Log</a></body></html>"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{severity}] Jenkins failed — {job_name} #{build_number}"
    msg["From"]    = "cibot@example.com"
    msg["To"]      = to_address
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.sendmail("cibot@example.com", [to_address], msg.as_string())
