"""Turn the deleting commit's subject into a cause of death."""

from __future__ import annotations

import re

_CONVENTIONAL = re.compile(r"^\s*([a-z]+)(?:\([^)]*\))?!?:", re.IGNORECASE)

_BY_TYPE = {
    "refactor": "refactored out of existence",
    "chore": "swept up in a chore",
    "fix": "was the bug",
    "feat": "made room for a feature",
    "revert": "reverted, never happened",
    "docs": "documentation casualty",
    "test": "test casualty",
    "ci": "build system cleanup",
    "build": "build system cleanup",
    "perf": "sacrificed for speed",
    "security": "removed for your safety",
    "style": "cosmetic complications",
}

_REMOVAL_WORDS = re.compile(
    r"\b(remove[sd]?|delete[sd]?|rm|drop(?:ped|s)?|clean(?:ed|s)?\s*up|cleanup|"
    r"purge[sd]?|prune[sd]?)\b",
    re.IGNORECASE,
)
_WIP = re.compile(r"^\s*wip\b", re.IGNORECASE)


def cause_of_death(subject: str) -> str:
    m = _CONVENTIONAL.match(subject)
    if m:
        cause = _BY_TYPE.get(m.group(1).lower())
        if cause:
            return cause
    if _WIP.match(subject):
        return "died of wip"
    if _REMOVAL_WORDS.search(subject):
        return "deliberately removed"
    return "unknown causes"
