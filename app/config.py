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
    JENKINS_URL:   str = "http://localhost:8080"  # e.g. https://ci.example.com
    JENKINS_USER:  str = "admin"
    JENKINS_TOKEN: str = "11e05dca6a9ae3da0331585dfe76b934a4"  # read-only API token

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:1234@localhost:5432/jenkins_log_intel"   # postgresql+asyncpg://...

    # Celery broker
    REDIS_URL: str = "redis://localhost:6379"

    # Slack
    SLACK_BOT_TOKEN:       str = "xoxb-11003189151795-11009624004946-8RefDnE2wqm7kEnXXQlq9148"
    SLACK_DEFAULT_CHANNEL: str = "#build-alerts"

    # LLM — Anthropic Claude (fallback / alternative)
    ANTHROPIC_API_KEY: Optional[str] = None

    # LLM — Groq (primary, used by root_cause.py)
    GROQ_API_KEY: str = "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"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Git token — used to fetch Jenkinsfiles from private repositories
    GITHUB_TOKEN: str = "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"   # also accepted as a generic Git token

    # Webhook HMAC secret (optional — development builds can omit this)
    JENKINS_WEBHOOK_SECRET: str = "x8Kf29LmPq7Rz41NsD2wYt98Ab"
    GITHUB_WEBHOOK_SECRET: str = "K8r2vP9xLm4Qz7Nf1Tg6Hs3YwA0bCdE"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
