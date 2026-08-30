import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from merge_step import (
    CONFLICT_ALERT_FLAG_TYPES,
    PART_ISSUE_FLAG_TYPES,
    WARNING_ONLY_FLAG_TYPES,
    run_merge_step,
)



def _packet(rule_violations=None, context_flags=None, ai_flags=None):
    return {
        "validation": {
            "rule_violations": rule_violations or [],
            "context_flags": context_flags or [],
            "ai_flags": ai_flags or {},
        }
    }


def _rule(severity):
    return {"rule_id": "R01", "severity": severity, "message": "Test rule"}


def _context(flag_type, severity="WARNING"):
    return {"flag_type": flag_type, "severity": severity, "message": "Test flag"}


def test_no_issues_passes_gate():
    result = run_merge_step(_packet())

    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["blockers"] == []
    assert result["gate"]["part_issues"] == []
    assert result["gate"]["conflict_alerts"] == []
    assert result["gate"]["warnings"] == []


def test_rule_error_fails_gate_and_is_blocker():
    violation = _rule("ERROR")
    result = run_merge_step(_packet(rule_violations=[violation]))

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["blockers"] == [violation]


def test_rule_warning_is_advisory_only():
    violation = _rule("WARNING")
    result = run_merge_step(_packet(rule_violations=[violation]))

    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["warnings"] == [violation]


def test_discontinued_part_fails_gate_as_part_issue():
    flag = _context("DISCONTINUED_PART", "ERROR")
    result = run_merge_step(_packet(context_flags=[flag]))

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["part_issues"] == [flag]


def test_missing_supplier_fails_gate_as_part_issue():
    flag = _context("MISSING_SUPPLIER", "ERROR")
    result = run_merge_step(_packet(context_flags=[flag]))

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["part_issues"] == [flag]


def test_uom_mismatch_fails_gate_as_part_issue():
    flag = _context("UOM_MISMATCH", "ERROR")
    result = run_merge_step(_packet(context_flags=[flag]))

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["part_issues"] == [flag]


def test_historical_conflict_fails_gate_as_an_error():
    flag = _context("HISTORICAL_CONFLICT", "ERROR")
    result = run_merge_step(_packet(context_flags=[flag]))

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["conflict_alerts"] == [flag]
    assert flag not in result["gate"]["warnings"]


def test_context_engine_flag_types_all_have_an_explicit_gate_classification():
    """New Context Engine flag types must be classified before they can ship."""
    source = (ROOT / "scripts" / "stages" / "context_engine.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    emitted_flag_types = {
        value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant)
        and key.value == "flag_type"
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
    }
    registered_flag_types = (
        PART_ISSUE_FLAG_TYPES
        | CONFLICT_ALERT_FLAG_TYPES
        | WARNING_ONLY_FLAG_TYPES
    )

    assert emitted_flag_types
    assert emitted_flag_types <= registered_flag_types


def test_unclassified_context_flag_raises_an_error():
    with pytest.raises(ValueError, match="Unclassified context flag_type"):
        run_merge_step(_packet(context_flags=[_context("UNREGISTERED_FLAG")]))


def test_other_context_flags_are_advisory_warnings():

    unknown_part = _context("UNKNOWN_PART")
    quantity_anomaly = _context("QUANTITY_ANOMALY")
    result = run_merge_step(_packet(context_flags=[unknown_part, quantity_anomaly]))

    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["warnings"] == [unknown_part, quantity_anomaly]


def test_ai_notes_never_change_gate_decision():
    ai_flags = {
        "overall_risk": "HIGH",
        "flags": [{"type": "CONTRADICTION"}],
        "recommendation": "Review the ECN.",
        "confidence": 0.91,
        "ai_available": True,
    }
    result = run_merge_step(_packet(ai_flags=ai_flags))

    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["ai_notes"] == {
        "mismatch_flag": True,
        "flags": ai_flags["flags"],
        "recommendation": ai_flags["recommendation"],
        "confidence": 0.91,
        "ai_available": True,
    }


def test_each_gate_category_is_aggregated_together():
    blocker = _rule("ERROR")
    part_issue = _context("DISCONTINUED_PART", "ERROR")
    conflict = _context("HISTORICAL_CONFLICT", "ERROR")
    warning = _context("DESCRIPTION_MISMATCH", "WARNING")
    result = run_merge_step(
        _packet(
            rule_violations=[blocker],
            context_flags=[part_issue, conflict, warning],
        )
    )

    assert result["gate"]["decision"] == "FAIL"
    assert result["gate"]["blockers"] == [blocker]
    assert result["gate"]["part_issues"] == [part_issue]
    assert result["gate"]["conflict_alerts"] == [conflict]
    assert result["gate"]["warnings"] == [warning]
