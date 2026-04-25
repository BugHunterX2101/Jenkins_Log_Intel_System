"""Integration tests for the /jobs router endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


TRIGGER_PAYLOAD = {
    "repo_url": "https://github.com/acme/my-service",
    "branch": "main",
    "commit_sha": "abc1234",
    "author": "alice@acme.com",
    "triggered_by": "test-suite",
}


def test_trigger_endpoint_queues_run(client):
    mock_run = MagicMock()
    mock_run.id = 99
    mock_run.status.value = "QUEUED"
    mock_run.jenkins_job_name = "acme/my-service/main"
    mock_run.stage_names = ["Checkout", "Test", "Build", "Deploy"]

    with patch("app.routers.jobs.schedule_pipeline", new_callable=AsyncMock, return_value=mock_run):
        resp = client.post(
            "/jobs/trigger",
            content=json.dumps(TRIGGER_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["run_id"] == 99
    assert body["status"] == "QUEUED"
    assert "Checkout" in body["stages"]


def test_trigger_endpoint_requires_repo_url(client):
    with patch("app.routers.jobs.schedule_pipeline", new_callable=AsyncMock):
        resp = client.post(
            "/jobs/trigger",
            content=json.dumps({"branch": "main"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 422


def test_trigger_endpoint_requires_branch(client):
    with patch("app.routers.jobs.schedule_pipeline", new_callable=AsyncMock):
        resp = client.post(
            "/jobs/trigger",
            content=json.dumps({"repo_url": "https://github.com/acme/svc"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 422


def test_dashboard_returns_grouped_structure(client):
    mock_snapshot = {
        "QUEUED": [], "IN_PROGRESS": [],
        "COMPLETED": [], "FAILED": [], "ABORTED": [],
    }
    with patch("app.routers.jobs.get_dashboard_snapshot", new_callable=AsyncMock, return_value=mock_snapshot):
        resp = client.get("/jobs")

    assert resp.status_code == 200
    body = resp.json()
    assert "QUEUED" in body
    assert "IN_PROGRESS" in body
    assert "COMPLETED" in body
    assert "FAILED" in body


def test_run_detail_returns_run(client):
    mock_run = MagicMock()
    mock_run.id = 42
    mock_run.status.value = "IN_PROGRESS"
    mock_run.stages = []

    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch("app.routers.jobs._serialise_run", return_value={"id": 42, "status": "IN_PROGRESS", "stages": []}):
        resp = client.get("/jobs/42")

    assert resp.status_code == 200
    assert resp.json()["id"] == 42


def test_run_detail_404_for_missing(client):
    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=None):
        resp = client.get("/jobs/99999")
    assert resp.status_code == 404


def test_stage_event_started(client):
    mock_run = MagicMock()
    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch("app.routers.jobs.on_stage_started", new_callable=AsyncMock):
        resp = client.post(
            "/jobs/1/stage-event",
            content=json.dumps({"stage_name": "Build", "event": "started"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True


def test_stage_event_completed(client):
    mock_run = MagicMock()
    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=mock_run), \
         patch("app.routers.jobs.on_stage_completed", new_callable=AsyncMock):
        resp = client.post(
            "/jobs/1/stage-event",
            content=json.dumps({"stage_name": "Deploy", "event": "completed"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200


def test_stage_event_invalid_event(client):
    mock_run = MagicMock()
    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=mock_run):
        resp = client.post(
            "/jobs/1/stage-event",
            content=json.dumps({"stage_name": "Test", "event": "UNKNOWN_EVENT"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 400


def test_stage_event_404_for_missing_run(client):
    with patch("app.routers.jobs.get_run", new_callable=AsyncMock, return_value=None):
        resp = client.post(
            "/jobs/99999/stage-event",
            content=json.dumps({"stage_name": "Test", "event": "started"}),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 404
