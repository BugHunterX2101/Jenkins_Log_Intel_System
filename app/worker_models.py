"""
Worker ORM models — simulated CI worker pool.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerStatus(str, enum.Enum):
    IDLE    = "IDLE"
    BUSY    = "BUSY"
    OFFLINE = "OFFLINE"


class WorkerLanguage(str, enum.Enum):
    PYTHON     = "python"
    NODE       = "node"
    JAVA       = "java"
    GO         = "go"
    RUBY       = "ruby"
    GENERIC    = "generic"


class AssignmentStatus(str, enum.Enum):
    ASSIGNED  = "ASSIGNED"
    RUNNING   = "RUNNING"
    DONE      = "DONE"
    FAILED    = "FAILED"


class Worker(Base):
    """A simulated worker node that can execute pipeline jobs."""
    __tablename__ = "workers"

    id:          Mapped[int]    = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:        Mapped[str]    = mapped_column(String(64),  nullable=False, unique=True)
    language:    Mapped[WorkerLanguage] = mapped_column(
        Enum(WorkerLanguage, name="worker_language"), nullable=False
    )
    status:      Mapped[WorkerStatus]   = mapped_column(
        Enum(WorkerStatus, name="worker_status"), default=WorkerStatus.IDLE, nullable=False
    )
    load:        Mapped[float]  = mapped_column(Float, default=0.0)
    jobs_run:    Mapped[int]    = mapped_column(Integer, default=0)
    current_job: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    capabilities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    assignments: Mapped[list["WorkerAssignment"]] = relationship(
        "WorkerAssignment", back_populates="worker", cascade="all, delete-orphan"
    )


class WorkerAssignment(Base):
    """Records which worker is handling which pipeline run."""
    __tablename__ = "worker_assignments"

    id:        Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id:    Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"),       nullable=False, index=True)

    status:      Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="assignment_status"), default=AssignmentStatus.ASSIGNED
    )
    assigned_at:   Mapped[datetime]          = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s:    Mapped[Optional[int]]      = mapped_column(Integer, nullable=True)
    result:        Mapped[Optional[str]]      = mapped_column(String(32), nullable=True)

    worker: Mapped["Worker"] = relationship("Worker", back_populates="assignments")
