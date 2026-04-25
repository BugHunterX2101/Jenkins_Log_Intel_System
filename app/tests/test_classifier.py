"""Unit tests for the failure classifier."""

import pytest
from app.services.classifier import classify, FailureTag


def test_classify_flaky_test():
    log = "AssertionError: expected 200 got 500"
    tags = classify(log)
    assert len(tags) > 0
    assert any(t.category == "flaky_test" for t in tags)


def test_classify_env_issue():
    log = "Error: environment variable SECRET_KEY not found"
    tags = classify(log)
    assert any(t.category == "env_issue" for t in tags)


def test_classify_dependency_error():
    log = "ModuleNotFoundError: No module named 'requests'"
    tags = classify(log)
    assert any(t.category == "dependency_error" for t in tags)


def test_classify_infrastructure():
    log = "java.lang.OutOfMemoryError: GC overhead limit exceeded"
    tags = classify(log)
    assert any(t.category == "infrastructure" for t in tags)


def test_classify_unknown():
    log = "Something weird happened that matches no rules"
    tags = classify(log)
    assert len(tags) == 1
    assert tags[0].category == "unknown"
    assert tags[0].confidence == "LOW"


def test_classify_multiple_types_gives_medium_confidence():
    log = "AssertionError: test failed\nModuleNotFoundError: no module"
    tags = classify(log)
    assert all(t.confidence == "MEDIUM" for t in tags)


def test_classify_high_confidence_single_type():
    log = "AssertionError: test failed\nAnother assertion error here"
    tags = classify(log)
    matched_types = {t.category for t in tags}
    if len(matched_types) == 1:
        assert all(t.confidence == "HIGH" for t in tags)
