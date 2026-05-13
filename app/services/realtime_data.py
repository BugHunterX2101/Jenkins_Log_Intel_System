"""Helpers that keep live API responses free of demo/test records."""

from __future__ import annotations

from sqlalchemy import and_, not_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models import BuildEvent
from app.pipeline_models import PipelineRun


_NON_REAL_MARKERS = ("sample-repo", "fake", "dummy", "demo")


def real_pipeline_run_clause() -> ColumnElement[bool]:
    """SQLAlchemy filter for excluding known non-real pipeline seed/test data."""
    marker_checks = [
        PipelineRun.repo_url.ilike(f"%{marker}%")
        for marker in _NON_REAL_MARKERS
    ]
    return and_(
        not_(or_(*marker_checks)),
        PipelineRun.triggered_by != "test-suite",
    )


def real_build_event_clause() -> ColumnElement[bool]:
    """SQLAlchemy filter for excluding known non-real build event data."""
    marker_checks = [
        BuildEvent.job_name.ilike(f"%{marker}%")
        for marker in _NON_REAL_MARKERS
    ]
    return not_(or_(*marker_checks))
