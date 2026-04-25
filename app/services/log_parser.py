"""
Log Parser — ANSI stripping and error-block extraction.
"""

import re
from dataclasses import dataclass, field

_ANSI_ESCAPE  = re.compile(r"\x1B\[[0-9;]*[A-Za-z]|\r")
_ISO8601_PFX  = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\s*")
_EPOCH_PFX    = re.compile(r"^\d{10,13}\s+")
_ERROR_ANCHOR = re.compile(r"(ERROR|FATAL|Exception|caused by|Build step|exit code)", re.IGNORECASE)
_CTX          = 5


@dataclass
class ErrorBlock:
    anchor_line:    str
    context_before: list[str] = field(default_factory=list)
    context_after:  list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(self.context_before + [self.anchor_line] + self.context_after)


def _strip(text: str) -> str:
    cleaned = []
    for line in text.splitlines():
        line = _ANSI_ESCAPE.sub("", line)
        line = _ISO8601_PFX.sub("", line)
        line = _EPOCH_PFX.sub("", line)
        cleaned.append(line)
    return "\n".join(cleaned)


def parse(raw_log: str) -> list[ErrorBlock]:
    lines   = _strip(raw_log).splitlines()
    seen:   set[str] = set()
    blocks: list[ErrorBlock] = []

    for idx, line in enumerate(lines):
        if not _ERROR_ANCHOR.search(line):
            continue
        norm = line.strip()
        if norm in seen:
            continue
        seen.add(norm)
        blocks.append(ErrorBlock(
            anchor_line=norm,
            context_before=lines[max(0, idx - _CTX): idx],
            context_after=lines[idx + 1: idx + 1 + _CTX],
        ))
    return blocks
