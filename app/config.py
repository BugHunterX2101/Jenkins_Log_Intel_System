"""
Typed configuration loaded from environment variables.
All secrets are read from env vars; never stored in source files.
"""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Jenkins integration
    JENKINS_URL:   str   # e.g. https://ci.example.com
    JENKINS_USER:  str
    JENKINS_TOKEN: str   # read-only API token

    # Database
    DATABASE_URL: str    # postgresql+asyncpg://...

    # Celery broker
    REDIS_URL: str = "redis://localhost:6379"

    # Slack
    SLACK_BOT_TOKEN:       str
    SLACK_DEFAULT_CHANNEL: str = "#build-alerts"

    # LLM — Anthropic Claude (fallback / alternative)
    ANTHROPIC_API_KEY: Optional[str] = None

    # LLM — Groq (primary, used by root_cause.py)
    GROQ_API_KEY: Optional[str] = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Git token — used to fetch Jenkinsfiles from private repositories
    GITHUB_TOKEN: Optional[str] = None   # also accepted as a generic Git token

    # Webhook HMAC secret (optional — development builds can omit this)
    JENKINS_WEBHOOK_SECRET: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
