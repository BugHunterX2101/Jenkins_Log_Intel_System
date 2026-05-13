"""Priority scheduling checks for a 3-repository, 6-branch push matrix."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
from app.pipeline_models import PipelineRun, RunStatus, branch_priority_expr
from app.services.priority import calculate_pipeline_priority


TEST_REPO_BRANCHES = [
    ("https://github.com/BugHunterX2101/test-1", "hotfix/auth-crash"),
    ("https://github.com/BugHunterX2101/test-1", "main"),
    ("https://github.com/BugHunterX2101/test-2", "release/v1.0"),
    ("https://github.com/BugHunterX2101/test-2", "develop"),
    ("https://github.com/BugHunterX2101/test-3", "feature/log-streaming"),
    ("https://github.com/BugHunterX2101/test-3", "experiment/queue-telemetry"),
]


def test_priority_scheduler_orders_real_test_branches_by_dispatch_priority():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    base_time = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        for idx, (repo_url, branch) in enumerate(TEST_REPO_BRANCHES):
            priority = calculate_pipeline_priority(repo_url, branch)
            session.add(
                PipelineRun(
                    repo_url=repo_url,
                    branch=branch,
                    triggered_by="priority-test",
                    status=RunStatus.QUEUED,
                    queued_at=base_time + timedelta(seconds=idx),
                    scheduling_priority=priority.value,
                    priority_reason=priority.reason,
                )
            )
        session.commit()

        rows = session.execute(
            select(PipelineRun.repo_url, PipelineRun.branch)
            .where(PipelineRun.status == RunStatus.QUEUED)
            .order_by(branch_priority_expr(), PipelineRun.queued_at.asc())
        ).all()

    assert rows == [
        ("https://github.com/BugHunterX2101/test-1", "hotfix/auth-crash"),
        ("https://github.com/BugHunterX2101/test-1", "main"),
        ("https://github.com/BugHunterX2101/test-2", "release/v1.0"),
        ("https://github.com/BugHunterX2101/test-2", "develop"),
        ("https://github.com/BugHunterX2101/test-3", "feature/log-streaming"),
        ("https://github.com/BugHunterX2101/test-3", "experiment/queue-telemetry"),
    ]


def test_priority_policy_can_promote_ci_and_production_file_changes():
    ci_priority = calculate_pipeline_priority(
        "https://github.com/BugHunterX2101/test-3",
        "feature/log-streaming",
        ["Jenkinsfile"],
    )
    prod_priority = calculate_pipeline_priority(
        "https://github.com/BugHunterX2101/test-2",
        "feature/billing-checkout",
        ["billing/invoice.py"],
    )

    assert ci_priority.value == 3
    assert ci_priority.reason == "CI/CD or infrastructure files changed"
    assert prod_priority.value == 2
    assert prod_priority.reason == "production-sensitive files changed"
