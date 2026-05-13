"""Tests for the Jenkins webhook endpoint."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch
import pytest


FAILURE_PAYLOAD = {
    "name": "my-service",
    "build": {
        "phase": "FINALIZED",
        "status": "FAILURE",
        "number": 42,
        "full_url": "http://jenkins.test/job/my-service/42/",
        "full_display_name": "my-service #42",
    }
}

SUCCESS_PAYLOAD = {
    "name": "my-service",
    "build": {
        "phase": "FINALIZED",
        "status": "SUCCESS",
        "number": 43,
        "full_url": "http://jenkins.test/job/my-service/43/",
    }
}


def test_webhook_accepts_failure_event(client):
    # BUG FIX: The route schedules async failure processing. Mock that hook so
    # the test verifies the endpoint contract without fetching Jenkins logs.
    with patch(
        "app.routers.webhook._schedule_failure_processing_async",
        new_callable=AsyncMock,
    ), patch(
        "app.routers.webhook._handle_build_completion",
        new_callable=AsyncMock,
    ):
        resp = client.post(
            "/webhook/jenkins",
            content=json.dumps(FAILURE_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["received"] is True


def test_webhook_accepts_success_event(client):
    with patch(
        "app.routers.webhook._handle_build_completion",
        new_callable=AsyncMock,
    ):
        resp = client.post(
            "/webhook/jenkins",
            content=json.dumps(SUCCESS_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["received"] is True


def test_webhook_rejects_invalid_signature():
    """When JENKINS_WEBHOOK_SECRET is set, bad sig should fail."""
    import app.routers.webhook as wh_module
    original = wh_module._WEBHOOK_SECRET
    wh_module._WEBHOOK_SECRET = "real-secret"
    try:
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.post(
                "/webhook/jenkins",
                content=json.dumps(FAILURE_PAYLOAD),
                headers={
                    "Content-Type": "application/json",
                    "X-Jenkins-Signature": "sha256=bad-signature",
                },
            )
        assert resp.status_code == 401
    finally:
        wh_module._WEBHOOK_SECRET = original
