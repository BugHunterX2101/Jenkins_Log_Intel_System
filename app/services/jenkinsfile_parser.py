"""
Jenkinsfile Parser — fetches a Jenkinsfile from a Git repository and
extracts the ordered list of stage names defined in the pipeline.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_STAGE_RE = re.compile(
    r"""stage\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.IGNORECASE,
)

_GITHUB_RE    = re.compile(r"github\.com/([^/]+/[^/]+?)(?:\.git)?$", re.IGNORECASE)
_GITLAB_RE    = re.compile(r"gitlab\.com/([^/]+/[^/?#]+?)(?:\.git)?$", re.IGNORECASE)
_BITBUCKET_RE = re.compile(r"bitbucket\.org/([^/]+/[^/?#]+?)(?:\.git)?$", re.IGNORECASE)


def _raw_url(repo_url: str, branch: str, path: str = "Jenkinsfile") -> str | None:
    m = _GITHUB_RE.search(repo_url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{branch}/{path}"

    m = _GITLAB_RE.search(repo_url)
    if m:
        slug = m.group(1).replace("/", "%2F")
        return (
            f"https://gitlab.com/api/v4/projects/{slug}/repository/files/"
            f"{path}/raw?ref={branch}"
        )

    m = _BITBUCKET_RE.search(repo_url)
    if m:
        return (
            f"https://api.bitbucket.org/2.0/repositories/{m.group(1)}"
            f"/src/{branch}/{path}"
        )

    return None


async def fetch_jenkinsfile(
    repo_url: str,
    branch: str,
    token: str | None = None,
    timeout: int = 15,
) -> str | None:
    raw_url = _raw_url(repo_url, branch)
    if not raw_url:
        logger.warning("Cannot derive raw URL for repo: %s", repo_url)
        return None

    headers: dict[str, str] = {}
    if token:
        if "gitlab.com" in raw_url:
            headers["PRIVATE-TOKEN"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(raw_url, headers=headers, follow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            logger.warning(
                "Jenkinsfile fetch returned HTTP %d for %s@%s",
                resp.status_code, repo_url, branch,
            )
    except httpx.RequestError as exc:
        logger.warning("Jenkinsfile fetch failed: %s", exc)

    return None


def parse_stages(jenkinsfile_text: str) -> list[str]:
    seen: set[str] = set()
    stages: list[str] = []
    for match in _STAGE_RE.finditer(jenkinsfile_text):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            stages.append(name)
    return stages


async def get_pipeline_stages(
    repo_url: str,
    branch: str,
    token: str | None = None,
) -> list[str]:
    text = await fetch_jenkinsfile(repo_url, branch, token=token)
    if not text:
        return []
    stages = parse_stages(text)
    logger.info("Parsed %d stages from %s@%s: %s", len(stages), repo_url, branch, stages)
    return stages
