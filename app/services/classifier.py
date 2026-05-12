"""
Failure Classifier — regex / rule-based engine.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_RULES_PATH = Path(__file__).resolve().parents[2] / "rules" / "classifier_rules.yaml"
logger = logging.getLogger(__name__)


@dataclass
class FailureTag:
    category:     str
    confidence:   str   # HIGH | MEDIUM | LOW
    matched_line: str
    matched_rule: str


def _load_rules() -> list[dict]:
    if not _RULES_PATH.exists():
        logger.warning("Classifier rules file not found: %s — no rules loaded", _RULES_PATH)
        return []
    try:
        with _RULES_PATH.open() as fh:
            raw = yaml.safe_load(fh)
        return [
            {"name": e["name"], "pattern": re.compile(e["pattern"], re.IGNORECASE), "failure_type": e["failure_type"]}
            for e in raw.get("rules", [])
        ]
    except Exception as exc:
        logger.error("Failed to load classifier rules from %s: %s", _RULES_PATH, exc)
        return []


_RULES: list[dict] = _load_rules()


def classify(log: str) -> list[FailureTag]:
    tags:          list[FailureTag] = []
    matched_types: set[str]         = set()

    for line in log.splitlines():
        for rule in _RULES:
            if rule["pattern"].search(line):
                matched_types.add(rule["failure_type"])
                tags.append(FailureTag(
                    category=rule["failure_type"], confidence="HIGH",
                    matched_line=line.strip(), matched_rule=rule["name"],
                ))

    if not tags:
        return [FailureTag(category="unknown", confidence="LOW", matched_line="", matched_rule="catch-all")]

    if len(matched_types) > 1:
        for tag in tags:
            tag.confidence = "MEDIUM"

    return tags
