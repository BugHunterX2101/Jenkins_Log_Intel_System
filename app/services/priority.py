"""Deterministic priority policy for git-triggered pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PipelinePriority:
    value: int
    label: str
    reason: str


_LABELS = {
    1: "P1 - Hotfix",
    2: "P2 - Production",
    3: "P3 - Release/CI",
    4: "P4 - Develop",
    5: "P5 - Feature",
    6: "P6 - Normal",
}

_CRITICAL_PATH_MARKERS = (
    "jenkinsfile",
    ".github/workflows/",
    "dockerfile",
    "docker-compose",
    "k8s/",
    "kubernetes/",
    "helm/",
    "terraform/",
    "infra/",
)

_PRODUCTION_PATH_MARKERS = (
    "auth/",
    "security/",
    "payment/",
    "billing/",
    "prod/",
)


def priority_label(value: int) -> str:
    return _LABELS.get(value, _LABELS[6])


def calculate_pipeline_priority(
    repo_url: str,
    branch: str,
    changed_files: Iterable[str] | None = None,
) -> PipelinePriority:
    """Assign a stable priority to every git push using explicit criteria.

    Lower numbers run first. The branch class is the primary signal because it
    is always available for a push. Changed file paths can promote a run when
    the push touches production-sensitive or CI/CD infrastructure files.
    """
    del repo_url  # Reserved for future repo-tier rules without changing callers.

    branch_name = (branch or "").strip()
    branch_key = branch_name.lower()
    files = [path.lower().replace("\\", "/") for path in (changed_files or [])]

    if branch_key.startswith("hotfix/") or "security" in branch_key:
        return PipelinePriority(1, priority_label(1), "hotfix/security branch")

    if branch_key in ("main", "master"):
        return PipelinePriority(2, priority_label(2), "production branch")

    if any(marker in path for path in files for marker in _PRODUCTION_PATH_MARKERS):
        return PipelinePriority(2, priority_label(2), "production-sensitive files changed")

    if branch_key.startswith("release/"):
        return PipelinePriority(3, priority_label(3), "release branch")

    if any(marker in path for path in files for marker in _CRITICAL_PATH_MARKERS):
        return PipelinePriority(3, priority_label(3), "CI/CD or infrastructure files changed")

    if branch_key == "develop":
        return PipelinePriority(4, priority_label(4), "develop integration branch")

    if branch_key.startswith("feature/"):
        return PipelinePriority(5, priority_label(5), "feature branch")

    return PipelinePriority(6, priority_label(6), "default branch priority")
