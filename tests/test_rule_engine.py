import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from rule_engine import EVALUATOR_REGISTRY, UnknownRuleEvaluatorError, run_rule_engine
from intake import build_ecn_packet, REQUIRED_ECN_FIELDS


def _base_packet(bom=None, header_overrides=None):
    header = {f: "val" for f in REQUIRED_ECN_FIELDS}
    header.update({"change_notice_number": "ECN-001", "date": "2024-01-01",
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


@pytest.mark.parametrize("row", [
    {"part_number": "", "quantity": "1", "line_number": "1"},
    {"quantity": "1", "line_number": "1"},
])
def test_R02_allows_missing_part_number(row):
    result = run_rule_engine(_base_packet(bom=[row]))

    assert not _violations(result, "R02")


def test_H12_duplicate_parts():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "1", "line_number": "1"},
        {"part_number": "12345", "quantity": "2", "line_number": "2"},
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "H12")


def test_H11_zero_quantity():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "0", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "H11")


def test_H11_negative_quantity():
    packet = _base_packet(bom=[
        {"part_number": "12345", "quantity": "-1", "line_number": "1"}
    ])
    result = run_rule_engine(packet)
    assert _violations(result, "H11")


def test_H03_checks_only_configured_form_headers():
    packet = _base_packet(header_overrides={
        "a3_number": "", "associated_a3": "", "change_actions": "",
        "cost_impact": "", "products_affected": "", "description_of_change": "",
        "date": "07/15/2024", "change_type": "destroy",
    })
    result = run_rule_engine(packet)
    violations = result["validation"]["rule_violations"]

    assert [item["location"]["field"] for item in _violations(result, "H03")] == [
        "header.description_of_change"
    ]
    assert not any(
        item.get("location", {}).get("field") in {
            "a3_number", "associated_a3", "change_actions", "cost_impact",
            "products_affected", "date", "change_type",
        }
        for item in violations
    )


def test_catalogue_finding_uses_the_unified_contract():
    result = run_rule_engine(_base_packet(header_overrides={"description_of_change": ""}))
    finding = _violations(result, "H03")[0]

    assert finding["rule_version"] == "1.0.0"
    assert finding["gate_effect"] == "FAIL"
    assert finding["location"] == {"field": "header.description_of_change"}
    assert finding["evidence"] == {"field": "description_of_change"}


def test_active_rule_without_a_registered_evaluator_fails_loudly(monkeypatch):
    monkeypatch.delitem(EVALUATOR_REGISTRY, "required")

    with pytest.raises(UnknownRuleEvaluatorError, match="H01"):
        run_rule_engine(_base_packet())