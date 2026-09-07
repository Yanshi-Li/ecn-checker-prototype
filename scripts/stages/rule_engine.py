"""Stage 2: catalogue-driven deterministic rule engine."""


from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from rule_catalogue import load_rule_catalogue, rules_for_engine


PART_NUMBER_PATTERN = re.compile(r"^\d{5,6}$")
Evaluator = Callable[[dict, dict], list[dict]]


class UnknownRuleEvaluatorError(ValueError):
    """Raised when active catalogue policy names an unregistered check."""


def _value(packet: dict, path: str) -> Any:
    """Read a dotted canonical path, with compatibility for flat BOM fields."""
    parts = path.split(".")
    current: Any = packet
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""
    return current


def _header_value(packet: dict, path: str) -> Any:
    """Read a rule field from the packet, including nested ECN headers."""
    if path.startswith("header."):
        return _value(packet, path)
    return _value(packet, path)



def _applies(packet: dict, rule: dict, row: dict | None = None) -> bool:
    condition = rule.get("applies_when")
    if not condition:
        return True
    source = {**packet, "bom": row or packet.get("bom", [])}
    field = condition.get("field")
    actual = _value(source, field) if field else _value(source, condition.get("left", ""))
    operator = condition.get("operator")
    if operator == "present":
        return bool(actual)
    if operator == "equals":
        return actual == condition.get("value")
    if operator == "not_equals":
        return actual != condition.get("value")
    if operator == "in":
        return actual in condition.get("values", [])
    if operator == "not_in":
        return actual not in condition.get("values", [])
    if operator == "equals_field":
        return actual == _value(source, condition.get("right", ""))
    raise ValueError(f"Unsupported applicability operator {operator!r} for {rule['id']}")


def _finding(rule: dict, catalogue: dict, *, location: dict, message: str,
             expected: Any, actual: Any, evidence: dict) -> dict:
    location_key = location.get("line_number", "ecn")
    return {
        "finding_id": f"{rule['id']}:{location_key}:{location.get('field', 'rule')}",
        "rule_id": rule["id"],
        "rule_version": catalogue["schema_version"],
        "evaluation_status": "FAIL",
        "severity": rule["severity"],
        "gate_effect": rule["gate_effect"],
        "source_engine": "rule_engine",
        "scope": rule["scope"],
        "location": location,
        "message": message,
        "expected": expected,
        "actual": actual,
        "evidence": evidence,
        "review_required": rule["gate_effect"] != "NONE",
    }


def evaluate_required(packet: dict, rule: dict, catalogue: dict) -> list[dict]:
    value = _header_value(packet, rule["field"])
    if value:
        return []
    field = rule["field"].removeprefix("header.")
    return [_finding(rule, catalogue, location={"field": rule["field"]},
                     message=rule["message"], expected="present", actual=value,
                     evidence={"field": field})]


def evaluate_no_duplicate_change_lines(packet: dict, rule: dict, catalogue: dict) -> list[dict]:
    seen: dict[str, list[Any]] = defaultdict(list)
    for row in packet.get("bom", []):
        part = row.get("part_number", "").strip()
        if part:
            seen[part].append(row.get("line_number", "?"))
    return [
        _finding(rule, catalogue,
                 location={"field": "bom.part_number", "line_numbers": lines},
                 message=rule["message"], expected="unique part number",
                 actual=part, evidence={"part_number": part, "line_numbers": lines})
        for part, lines in seen.items() if len(lines) > 1
    ]


def evaluate_positive_decimal(packet: dict, rule: dict, catalogue: dict) -> list[dict]:
    findings = []
    parameters = rule.get("parameters", {})
    minimum = parameters.get("minimum_exclusive", 0)
    max_places = parameters.get("maximum_decimal_places", 5)
    for row in packet.get("bom", []):
        if not _applies(packet, rule, row):
            continue
        raw = str(row.get("quantity", "")).strip()
        try:
            value = float(raw)
            invalid = value <= minimum or ("." in raw and len(raw.split(".", 1)[1]) > max_places)
        except (TypeError, ValueError):
            invalid = True
        if invalid:
            line = row.get("line_number", "?")
            findings.append(_finding(
                rule, catalogue, location={"line_number": line, "field": "bom.quantity"},
                message=rule["message"], expected=f"> {minimum}, max {max_places} decimal places",
                actual=raw, evidence={"line_number": line, "quantity": raw},
            ))
    return findings


def evaluate_compatibility_part_number(packet: dict) -> list[dict]:
    """R02 remains temporary: rules_origin has no canonical part-format rule."""
    findings = []
    for row in packet.get("bom", []):
        part = row.get("part_number", "").strip()
        if part and not PART_NUMBER_PATTERN.fullmatch(part):
            findings.append({
                "rule_id": "R02", "legacy_rule_id": "R02", "severity": "ERROR", "gate_effect": "FAIL",
                "field": "part_number", "line": row.get("line_number", "?"),
                "value": part,
                "message": f"Part number '{part}' on line {row.get('line_number', '?')} must contain 5 or 6 digits when provided (e.g. 12345 or 123456).",
            })
    return findings


EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    "required": evaluate_required,
    "no_duplicate_change_lines": evaluate_no_duplicate_change_lines,
    "positive_decimal": evaluate_positive_decimal,
}


def run_rule_engine(packet: dict) -> dict:
    """Execute active catalogue rules and the explicit R02 compatibility rule."""
    catalogue = load_rule_catalogue()
    violations = []
    for rule in rules_for_engine("rule_engine", catalogue):
        evaluator = EVALUATOR_REGISTRY.get(rule["check"])
        if evaluator is None:
            raise UnknownRuleEvaluatorError(
                f"Rule {rule['id']} references unknown rule-engine evaluator {rule['check']!r}."
            )
        violations.extend(evaluator(packet, rule, catalogue))
    violations.extend(evaluate_compatibility_part_number(packet))
    packet["validation"]["rule_violations"] = violations
    return packet