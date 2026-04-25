"""
Pipeline ORM models — Job scheduling and stage-level execution tracking.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, enum.Enum):
    QUEUED      = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED   = "COMPLETED"
    FAILED      = "FAILED"
    ABORTED     = "ABORTED"


class StageStatus(str, enum.Enum):
    PENDING    = "PENDING"
    RUNNING    = "RUNNING"
    SUCCESS    = "SUCCESS"
    FAILED     = "FAILED"
    SKIPPED    = "SKIPPED"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    repo_url:    Mapped[str] = mapped_column(String(1024), nullable=False)
    branch:      Mapped[str] = mapped_column(String(256),  nullable=False)
    commit_sha:  Mapped[Optional[str]] = mapped_column(String(40),  nullable=True)
    author:      Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(256), nullable=False, default="api")

    jenkins_job_name:    Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    jenkins_build_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jenkins_build_url:   Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    status:     Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), default=RunStatus.QUEUED, nullable=False
    )
    queued_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    stage_names_csv: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    result:       Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    duration_s:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    stages: Mapped[list["StageExecution"]] = relationship(
        "StageExecution", back_populates="run", cascade="all, delete-orphan",
        order_by="StageExecution.order"
    )

    @property
    def stage_names(self) -> list[str]:
        if not self.stage_names_csv:
            return []
        return [s.strip() for s in self.stage_names_csv.split(",") if s.strip()]


class StageExecution(Base):
    __tablename__ = "stage_executions"

    id:     Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    order:  Mapped[int] = mapped_column(Integer, nullable=False)
    name:   Mapped[str] = mapped_column(String(256), nullable=False)

    status:     Mapped[StageStatus] = mapped_column(
        Enum(StageStatus, name="stage_status"), default=StageStatus.PENDING, nullable=False
    )
    started_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    log_excerpt:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="stages")
