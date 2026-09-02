import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from rule_engine import run_rule_engine
from intake import build_ecn_packet, REQUIRED_ECN_FIELDS


def _base_packet(bom=None, header_overrides=None):
    header = {f: "val" for f in REQUIRED_ECN_FIELDS}
    header.update({"ecn_id": "ECN-001", "date": "2024-01-01",
                   "change_type": "add", **(header_overrides or {})})
    return build_ecn_packet([header], bom or [])


def _violations(packet, rule_id):
    return [v for v in packet["validation"]["rule_violations"]
            if v["rule_id"] == rule_id]


def test_R02_bad_part_number():
    packet = _base_packet(bom=[
        {"part_number": "BADPN", "quantity": "1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert any(v["rule_id"] == "R02" for v in result["validation"]["rule_violations"])


@pytest.mark.parametrize("part_number", ["12345", "123456"])
def test_R02_good_part_number(part_number):
    packet = _base_packet(bom=[
        {"part_number": part_number, "quantity": "1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert not _violations(result, "R02")


@pytest.mark.parametrize("part_number", ["1234", "1234567", "AB-1234"])
def test_R02_rejects_part_numbers_outside_five_to_six_digits(part_number):
    packet = _base_packet(bom=[
        {"part_number": part_number, "quantity": "1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R02")


def test_R03_duplicate_parts():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "1", "line_number": "1"},
        {"part_number": "12345", "quantity": "2", "line_number": "2"},
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R03")


def test_R04_zero_quantity():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "0", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R04")


def test_R04_negative_quantity():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "-1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R04")


def test_R01_checks_only_configured_form_headers():
    packet = _base_packet(header_overrides={
        "cost_impact": "",
        "date": "07/15/2024",
        "change_type": "destroy",
    })
    result = run_rule_engine(packet)

    violations = result["validation"]["rule_violations"]
    assert [violation["field"] for violation in _violations(result, "R01")] == [
        "cost_impact"
    ]
    assert not any(violation["field"] in {"date", "change_type"} for violation in violations)