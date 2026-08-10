import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from ai_advisory import _rule_based_advisory
from intake import build_ecn_packet, REQUIRED_ECN_FIELDS


def _packet(description="", bom=None):
    header = {f: "val" for f in REQUIRED_ECN_FIELDS}
    header["description"] = description
    return build_ecn_packet([header], bom or [])


def test_fallback_vague_short_description():
    packet = _packet(description="fix")
    result = _rule_based_advisory(packet)
    assert result["description_quality"] == "VAGUE"
    assert any(f["type"] == "VAGUE_TEXT" for f in result["flags"])


def test_fallback_good_description():
    packet = _packet(
        description="Replacing capacitor AB-1234 with AB-5678 to resolve thermal failures."
    )
    result = _rule_based_advisory(packet)
    assert result["overall_risk"] in ("LOW", "MEDIUM")


def test_fallback_unmentioned_parts():
    packet = _packet(
        description="Updating the resistor assembly.",
        bom=[{"part_number": "AB-9999", "quantity": "1", "line_number": "1"}]
    )
    result = _rule_based_advisory(packet)
    assert any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])


def test_result_structure():
    packet = _packet(description="Some description text here for testing.")
    result = _rule_based_advisory(packet)
    assert "overall_risk" in result
    assert "description_quality" in result
    assert "flags" in result
    assert "recommendation" in result


# ── Tests reflecting ECN-2026-002 (cost reduction, well-formed) ──────────────

def test_ecn_2026_002_good_description():
    # ECN-2026-002 has a detailed, specific description — should not be VAGUE
    packet = _packet(
        description=(
            "Replace Resistor R301 (C-300) with lower-cost equivalent C-350 "
            "to reduce unit cost by 15%. Supplier-D has been qualified and approved."
        ),
        bom=[{"part_number": "C-300", "quantity": "4", "line_number": "1"},
             {"part_number": "C-350", "quantity": "4", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert result["description_quality"] != "VAGUE"
    assert result["overall_risk"] in ("LOW", "MEDIUM")


def test_ecn_2026_002_parts_mentioned_in_description():
    # Both C-300 and C-350 are referenced in the description — no MISSING_CONTEXT
    packet = _packet(
        description=(
            "Replacing C-300 resistor with C-350 low-cost alternative. "
            "Supplier-D qualified. 15% cost saving expected."
        ),
        bom=[{"part_number": "C-300", "quantity": "4", "line_number": "1"},
             {"part_number": "C-350", "quantity": "4", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert not any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])


# ── Tests reflecting ECN-2026-003 (stock shortage, blank description) ────────

def test_ecn_2026_003_blank_description_is_vague():
    # ECN-2026-003 has a blank description — must be flagged as VAGUE
    packet = _packet(description="")
    result = _rule_based_advisory(packet)
    assert result["description_quality"] == "VAGUE"
    assert any(f["type"] == "VAGUE_TEXT" for f in result["flags"])


def test_ecn_2026_003_unmentioned_parts_flagged():
    # C-200 and C-260 are in the BOM but description is blank — MISSING_CONTEXT expected
    packet = _packet(
        description="",
        bom=[{"part_number": "C-200", "quantity": "1", "line_number": "1"},
             {"part_number": "C-260", "quantity": "1", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])