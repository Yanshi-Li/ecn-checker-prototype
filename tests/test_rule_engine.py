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


def test_R02_good_part_number():
    packet = _base_packet(bom=[
        {"part_number": "AB-1234", "quantity": "1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert not _violations(result, "R02")


def test_R03_duplicate_parts():
    packet = _base_packet(bom=[
        {"part_number": "AB-1234", "quantity": "1", "line_number": "1"},
        {"part_number": "AB-1234", "quantity": "2", "line_number": "2"},
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R03")


def test_R04_zero_quantity():
    packet = _base_packet(bom=[
        {"part_number": "AB-1234", "quantity": "0", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R04")


def test_R04_negative_quantity():
    packet = _base_packet(bom=[
        {"part_number": "AB-1234", "quantity": "-1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "R04")


def test_R05_invalid_change_type():
    packet = _base_packet(header_overrides={"change_type": "destroy"})
    result = run_rule_engine(packet)
    assert _violations(result, "R05")


def test_R06_bad_date_format():
    packet = _base_packet(header_overrides={"date": "07/15/2024"})
    result = run_rule_engine(packet)
    assert _violations(result, "R06")