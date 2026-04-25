"""
Shared pytest fixtures.
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JENKINS_URL",              "http://jenkins.test")
os.environ.setdefault("JENKINS_USER",             "test-user")
os.environ.setdefault("JENKINS_TOKEN",            "test-token")
os.environ.setdefault("DATABASE_URL",             "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL",                "redis://localhost:6379")
os.environ.setdefault("SLACK_BOT_TOKEN",          "xoxb-test")
os.environ.setdefault("SLACK_DEFAULT_CHANNEL",    "#test")
os.environ.setdefault("ANTHROPIC_API_KEY",        "sk-ant-test")
os.environ.setdefault("GROQ_API_KEY",             "gsk_test")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET",    "test-secret")
os.environ.setdefault("JENKINS_WEBHOOK_SECRET",   "")


@pytest.fixture(scope="session")
def client():
    from main import app
    with TestClient(app) as c:
        yield c
