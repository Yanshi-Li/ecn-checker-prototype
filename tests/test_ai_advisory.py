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