"""Unit tests for the log parser."""

import pytest
from app.services.log_parser import parse, ErrorBlock


def test_parse_finds_error_anchor():
    log = "Some output\nERROR: Something went wrong\nMore output"
    blocks = parse(log)
    assert len(blocks) == 1
    assert "ERROR" in blocks[0].anchor_line


def test_parse_strips_ansi():
    log = "\x1b[31mERROR\x1b[0m: Something failed"
    blocks = parse(log)
    assert len(blocks) == 1
    assert "\x1b" not in blocks[0].anchor_line


def test_parse_strips_timestamps():
    log = "2024-01-15T10:30:00Z ERROR: Build failed"
    blocks = parse(log)
    assert len(blocks) == 1
    assert "2024" not in blocks[0].anchor_line


def test_parse_context_lines():
    lines = ["line1", "line2", "line3", "line4", "line5",
             "ERROR: failure here",
             "line7", "line8", "line9", "line10", "line11"]
    log = "\n".join(lines)
    blocks = parse(log)
    assert len(blocks) == 1
    assert len(blocks[0].context_before) <= 5
    assert len(blocks[0].context_after) <= 5


def test_parse_deduplicates():
    log = "ERROR: same error\nERROR: same error\nERROR: same error"
    blocks = parse(log)
    assert len(blocks) == 1


def test_parse_empty_log():
    blocks = parse("")
    assert blocks == []


def test_parse_full_text_property():
    log = "before\nERROR: something\nafter"
    blocks = parse(log)
    assert len(blocks) == 1
    assert "ERROR: something" in blocks[0].full_text


def test_parse_exception_anchor():
    log = "java.lang.NullPointerException: null\n  at com.example.Foo.bar(Foo.java:42)"
    blocks = parse(log)
    assert len(blocks) == 1
    assert "Exception" in blocks[0].anchor_line
