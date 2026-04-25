"""Tests for the Jenkins webhook endpoint."""

import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock
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
    # BUG FIX: The original test triggered the real background task which
    # makes network calls to jenkins.test. We must mock process_build_failure
    # so the test only verifies the endpoint's HTTP contract, not task execution.
    # The import happens inside the handler, so we patch at the source module.
    with patch("app.tasks.process_build_failure") as mock_task:
        resp = client.post(
            "/webhook/jenkins",
            content=json.dumps(FAILURE_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["received"] is True


def test_webhook_accepts_success_event(client):
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
