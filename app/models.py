"""
SQLAlchemy ORM models — core tables.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BuildEvent(Base):
    """One record per processed failed build (failure-analysis pipeline)."""

    __tablename__ = "build_events"

    id:               Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name:         Mapped[str]      = mapped_column(String(512), nullable=False)
    build_number:     Mapped[int]      = mapped_column(Integer, nullable=False)
    failure_type:     Mapped[str]      = mapped_column(String(64),  nullable=False)
    confidence:       Mapped[str]      = mapped_column(String(8),   nullable=False)
    summary_text:     Mapped[str]      = mapped_column(Text,        nullable=False)
    fix_suggestions:  Mapped[str]      = mapped_column(Text,        nullable=False)  # JSON array
    severity:         Mapped[str]      = mapped_column(String(4),   nullable=False)
    log_url:          Mapped[str]      = mapped_column(String(1024), nullable=False)
    delivery_status:  Mapped[str]      = mapped_column(String(16),  default="PENDING")
    log_truncated:    Mapped[bool]     = mapped_column(Boolean,     default=False)
    processed_at:     Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PatternRecord(Base):
    """Append-only store of normalised error signatures from historical builds."""

    __tablename__ = "pattern_records"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    signature_hash:   Mapped[str]           = mapped_column(String(64), unique=True, nullable=False)
    failure_type:     Mapped[str]           = mapped_column(String(64), nullable=False)
    raw_sample:       Mapped[str]           = mapped_column(Text,       nullable=False)
    resolution_text:  Mapped[str | None]    = mapped_column(Text,       nullable=True)
    occurrence_count: Mapped[int]           = mapped_column(Integer,    default=1)
    last_seen:        Mapped[datetime]      = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
