"""
Typed configuration loaded from environment variables.
All secrets are read from env vars; never stored in source files.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # Jenkins integration
    JENKINS_URL:   str = "http://localhost:8080"
    JENKINS_USER:  str = "admin"
    JENKINS_TOKEN: str = ""

    # Database — set via DATABASE_URL env var in production
    DATABASE_URL: str = "postgresql+asyncpg://postgres:1234@localhost:5432/jenkins_log_intel"

    # Celery broker
    REDIS_URL: str = "redis://localhost:6379"

    # Slack
    SLACK_BOT_TOKEN:       str = ""
    SLACK_DEFAULT_CHANNEL: str = "#build-alerts"

    # LLM — Anthropic Claude (fallback / alternative)
    ANTHROPIC_API_KEY: Optional[str] = None

    # LLM — Groq (primary, used by root_cause.py)
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Git token — used to fetch Jenkinsfiles from private repositories
    GITHUB_TOKEN: str = ""

    # Webhook HMAC secrets — omit or leave blank to disable signature verification
    JENKINS_WEBHOOK_SECRET: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
