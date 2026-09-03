import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rule_catalogue import (  # noqa: E402
    DEFAULT_CATALOGUE_PATH,
    RuleCatalogueError,
    load_rule_catalogue,
    rules_for_engine,
)


def test_active_catalogue_is_valid_and_contains_each_source_rule():
    catalogue = load_rule_catalogue()

    source_ids = {
        line.split("|")[1].strip()
        for line in (ROOT / "docs" / "rules_origin.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and len(line.split("|")) > 2
        and line.split("|")[1].strip()[:1] in {"H", "S", "D"}
    }
    catalogue_ids = {rule["id"] for rule in catalogue["rules"]}

    assert DEFAULT_CATALOGUE_PATH == ROOT / "docs" / "rules_list.json"
    assert catalogue["source"] == "docs/rules_origin.txt"
    assert len(catalogue["rules"]) == 32
    assert catalogue_ids == source_ids


def test_rules_are_assigned_to_their_owning_pipeline_stage():
    assert {rule["id"] for rule in rules_for_engine("rule_engine")} == {
        "H01", "H02", "H03", "H06", "H07", "H08", "H11", "H12",
        "H14", "H15", "H16", "H17", "H18", "H19", "H20", "H21", "H22",
    }
    assert {rule["id"] for rule in rules_for_engine("context_engine")} == {
        "H09", "H10", "H13", "D01", "D02", "D03", "D04",
    }
    assert {rule["id"] for rule in rules_for_engine("ai_advisory")} == {
        "H04", "H05", "H23", "S01", "S02", "S03", "S04", "S05",
    }


def test_catalogue_rejects_duplicate_rule_ids(tmp_path):
    invalid_catalogue = {
        "schema_version": "1.0.0",
        "rules": [
            {
                "id": "H01", "domain": "ECN_HEADER", "scope": "ecn",
                "evaluator": "deterministic", "check": "required",
                "field": "header.name_of_change", "severity": "BLOCKER",
                "gate_effect": "FAIL", "message": "Required",
            },
            {
                "id": "H01", "domain": "ECN_HEADER", "scope": "ecn",
                "evaluator": "deterministic", "check": "required",
                "field": "header.description_of_change", "severity": "BLOCKER",
                "gate_effect": "FAIL", "message": "Required",
            },
        ],
    }
    path = tmp_path / "duplicate-rules.json"
    path.write_text(json.dumps(invalid_catalogue), encoding="utf-8")

    with pytest.raises(RuleCatalogueError, match="Duplicate rule id"):
        load_rule_catalogue(path)


def test_catalogue_rejects_unsupported_evaluator(tmp_path):
    path = tmp_path / "invalid-evaluator.json"
    path.write_text(
        json.dumps({
            "schema_version": "1.0.0",
            "rules": [{
                "id": "X01", "domain": "ECN_HEADER", "scope": "ecn",
                "evaluator": "unsupported", "check": "required",
                "field": "header.name_of_change", "severity": "BLOCKER",
                "gate_effect": "FAIL", "message": "Required",
            }],
        }),
        encoding="utf-8",
    )

    with pytest.raises(RuleCatalogueError, match="unsupported evaluator"):
        load_rule_catalogue(path)
