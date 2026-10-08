"""Attempt naming and source-status helpers for evaluation persistence."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Optional


_ATTEMPT_NAME_PATTERN = re.compile(
    r"^(?P<ecn>\d+)_MBOM_(?P<status>DRAFT|COMPLETED)$",
)


def derive_source_status_from_path(path: str) -> str:
    """Return DRAFT/COMPLETED based on authoritative batch source folder."""
    normalized = path.replace("\\", "/").lower()
    parts = list(PurePosixPath(normalized).parts)
    if "ecn_draft" in parts:
        return "DRAFT"
    if "ecn_completed" in parts:
        return "COMPLETED"
    raise ValueError(f"unable to derive source status from path: {path}")


def parse_attempt_name(attempt_name: str) -> tuple[Optional[str], Optional[str]]:
    """Parse canonical attempt names like 4079118_MBOM_DRAFT."""
    match = _ATTEMPT_NAME_PATTERN.match(str(attempt_name or "").strip())
    if not match:
        return None, None
    return match.group("ecn"), match.group("status").upper()