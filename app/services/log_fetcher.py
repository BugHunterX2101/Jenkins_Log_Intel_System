"""
Jenkins REST API client.
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_LOG_BYTES = 10 * 1024 * 1024   # 10 MB
_RETRY_DELAYS  = (2, 4, 8)


async def fetch_console_log(job: str, build_number: int) -> str:
    url  = f"{settings.JENKINS_URL}/job/{job}/{build_number}/consoleText"
    auth = (settings.JENKINS_USER, settings.JENKINS_TOKEN)

    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, auth=auth)
                response.raise_for_status()

            raw = response.text
            if len(raw.encode()) > _MAX_LOG_BYTES:
                logger.warning("Log for %s#%s exceeds 10 MB; truncating.", job, build_number)
                raw = raw.encode()[-_MAX_LOG_BYTES:].decode(errors="replace")
            return raw

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed for %s#%s: %s",
                           attempt, len(_RETRY_DELAYS), job, build_number, exc)
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)

    raise RuntimeError(
        f"Failed to fetch log for {job}#{build_number} after {len(_RETRY_DELAYS)} attempts"
    ) from last_exc
