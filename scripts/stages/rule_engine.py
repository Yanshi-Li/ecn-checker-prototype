"""
Stage 2: Rule Engine
Validates the ECN packet against deterministic business rules.
Rule IDs are stable and referenced in the dashboard and tests.
"""

import re
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

PART_NUMBER_PATTERN = re.compile(r"^\d{5,6}$")


# ── Individual rules ─────────────────────────────────────────────────────────
def rule_R01_required_fields(packet: dict) -> list[dict]:
    """R01 — All required ECN header fields must be present and non-empty."""
    violations = []
    for field in packet["validation"]["missing_fields"]:
        violations.append({
            "rule_id": "R01",
            "severity": "ERROR",
            "field": field,
            "message": f"Required field '{field}' is missing or empty.",
        })
    return violations


def rule_R02_part_number_format(packet: dict) -> list[dict]:
    """R02 — Part numbers must contain exactly five or six digits."""
    violations = []
    for row in packet.get("bom", []):
        pn = row.get("part_number", "").strip()
        if pn and not PART_NUMBER_PATTERN.fullmatch(pn):
            violations.append({
                "rule_id": "R02",
                "severity": "ERROR",
                "field": "part_number",
                "line": row.get("line_number", "?"),
                "value": pn,
                "message": f"Part number '{pn}' on line {row.get('line_number', '?')} "
                           f"must contain exactly 5 or 6 digits (e.g. 12345 or 123456).",
            })
    return violations


def rule_R03_duplicate_lines(packet: dict) -> list[dict]:
    """R03 — No duplicate part numbers within the same BOM."""
    violations = []
    seen: dict[str, list] = defaultdict(list)

    for row in packet.get("bom", []):
        pn = row.get("part_number", "").strip()
        if pn:
            seen[pn].append(row.get("line_number", "?"))

    for pn, lines in seen.items():
        if len(lines) > 1:
            violations.append({
                "rule_id": "R03",
                "severity": "WARNING",
                "field": "part_number",
                "value": pn,
                "lines": lines,
                "message": f"Duplicate part number '{pn}' found on lines {lines}. "
                           f"Consolidate or verify intent.",
            })
    return violations


def rule_R04_zero_quantity(packet: dict) -> list[dict]:
    """R04 — BOM lines must not have zero or negative quantity."""
    violations = []
    for row in packet.get("bom", []):
        qty_raw = row.get("quantity", "").strip()
        try:
            qty = float(qty_raw)
            if qty <= 0:
                violations.append({
                    "rule_id": "R04",
                    "severity": "ERROR",
                    "field": "quantity",
                    "line": row.get("line_number", "?"),
                    "value": qty_raw,
                    "message": f"Line {row.get('line_number', '?')} has zero or "
                               f"negative quantity ({qty_raw}). Remove or correct this line.",
                })
        except ValueError:
            violations.append({
                "rule_id": "R04",
                "severity": "ERROR",
                "field": "quantity",
                "line": row.get("line_number", "?"),
                "value": qty_raw,
                "message": f"Line {row.get('line_number', '?')} has non-numeric "
                           f"quantity '{qty_raw}'.",
            })
    return violations


def rule_R05_change_type_valid(packet: dict) -> list[dict]:
    """R05 — Change type must be one of the approved values."""
    VALID_TYPES = {"add", "remove", "modify", "replace", "note"}
    violations = []
    change_type = packet["header"].get("change_type", "").strip().lower()
    if change_type and change_type not in VALID_TYPES:
        violations.append({
            "rule_id": "R05",
            "severity": "WARNING",
            "field": "change_type",
            "value": change_type,
            "message": f"Change type '{change_type}' is not in the approved list: "
                       f"{sorted(VALID_TYPES)}.",
        })
    return violations


def rule_R06_date_format(packet: dict) -> list[dict]:
    """R06 — ECN date must be in YYYY-MM-DD format."""
    violations = []
    date_val = packet["header"].get("date", "").strip()
    if date_val and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
        violations.append({
            "rule_id": "R06",
            "severity": "WARNING",
            "field": "date",
            "value": date_val,
            "message": f"Date '{date_val}' is not in required YYYY-MM-DD format.",
        })
    return violations


# ── Rule registry & runner ───────────────────────────────────────────────────
RULES = [
    rule_R01_required_fields,
    rule_R02_part_number_format,
    rule_R03_duplicate_lines,
    rule_R04_zero_quantity,
    rule_R05_change_type_valid,
    rule_R06_date_format,
]


def run_rule_engine(packet: dict) -> dict:
    """
    Run all rules against the ECN packet.
    Appends violations to packet['validation']['rule_violations'].
    Returns the updated packet.
    """
    all_violations = []
    for rule_fn in RULES:
        violations = rule_fn(packet)
        all_violations.extend(violations)
        if violations:
            logger.warning(
                "%s triggered %d violation(s)", rule_fn.__name__, len(violations)
            )

    packet["validation"]["rule_violations"] = all_violations

    error_count = sum(1 for v in all_violations if v["severity"] == "ERROR")
    warn_count = sum(1 for v in all_violations if v["severity"] == "WARNING")
    logger.info(
        "Rule Engine complete — %d error(s), %d warning(s)", error_count, warn_count
    )
    return packet