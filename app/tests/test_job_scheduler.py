"""Unit tests for job_scheduler helpers (no DB required)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.services.job_scheduler import _derive_job_name, serialise_run, _serialise_stage
from app.pipeline_models import PipelineRun, StageExecution, RunStatus, StageStatus


def test_derive_job_name_github():
    name = _derive_job_name("https://github.com/acme/my-service", "main")
    assert name == "acme/my-service/main"


def test_derive_job_name_strips_git_suffix():
    name = _derive_job_name("https://github.com/acme/my-service.git", "develop")
    assert "my-service" in name
    assert "develop" in name


def test_derive_job_name_feature_branch():
    name = _derive_job_name("https://github.com/acme/svc", "feature/cool-stuff")
    assert name == "acme/svc/feature/cool-stuff"


def test_derive_job_name_short_url():
    name = _derive_job_name("https://ci.local/repo", "main")
    assert "main" in name


def _make_stage(**kwargs):
    defaults = dict(
        id=1, run_id=1, order=0, name="Test",
        status=StageStatus.PENDING,
        started_at=None, completed_at=None,
        duration_s=None, log_excerpt=None,
    )
    defaults.update(kwargs)
    stage = MagicMock(spec=StageExecution)
    for k, v in defaults.items():
        setattr(stage, k, v)
    return stage


def test_serialise_stage_pending():
    s = _make_stage(status=StageStatus.PENDING)
    d = _serialise_stage(s)
    assert d["status"] == "PENDING"
    assert d["duration_s"] is None


def test_serialise_stage_success():
    now = datetime.now(timezone.utc)
    s = _make_stage(status=StageStatus.SUCCESS, started_at=now, completed_at=now, duration_s=42)
    d = _serialise_stage(s)
    assert d["status"] == "SUCCESS"
    assert d["duration_s"] == 42


def test_serialise_stage_has_log():
    s = _make_stage(status=StageStatus.FAILED, log_excerpt="ERROR: boom")
    d = _serialise_stage(s)
    assert d["log_excerpt"] == "ERROR: boom"


def _make_run(**kwargs):
    defaults = dict(
        id=1, repo_url="https://github.com/acme/svc", branch="main",
        commit_sha="abc123", author="alice@acme.com", triggered_by="api",
        jenkins_job_name="acme/svc/main", jenkins_build_number=42,
        jenkins_build_url="https://ci.example.com/job/acme/svc/main/42/",
        status=RunStatus.IN_PROGRESS, result=None,
        queued_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        completed_at=None, duration_s=None,
        stages=[],
    )
    defaults.update(kwargs)
    run = MagicMock(spec=PipelineRun)
    for k, v in defaults.items():
        setattr(run, k, v)
    return run


def testserialise_run_fields():
    run = _make_run()
    d = serialise_run(run)
    assert d["id"] == 1
    assert d["branch"] == "main"
    assert d["status"] == "IN_PROGRESS"
    assert d["stages"] == []


def testserialise_run_with_stages():
    stage = _make_stage(name="Build", status=StageStatus.SUCCESS, duration_s=10)
    run = _make_run(stages=[stage])
    d = serialise_run(run)
    assert len(d["stages"]) == 1
    assert d["stages"][0]["name"] == "Build"


def testserialise_run_queued_at_iso():
    run = _make_run()
    d = serialise_run(run)
    assert "T" in d["queued_at"]
