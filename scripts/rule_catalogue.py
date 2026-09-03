"""Load and validate the versioned ECN rule catalogue.

The active policy data lives in ``docs/rules_list.json``. Pipeline stages use
this module rather than opening the JSON file directly, so invalid policy data
fails fast and every stage uses the same rule-ownership definitions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOGUE_PATH = ROOT / "docs" / "rules_list.json"

REQUIRED_RULE_FIELDS = {
    "id",
    "domain",
    "scope",
    "evaluator",
    "check",
    "severity",
    "gate_effect",
    "message",
}
VALID_EVALUATORS = {
    "deterministic",
    "reference_lookup",
    "semantic_heuristic",
    "llm_advisory",
}
VALID_SEVERITIES = {"BLOCKER", "WARNING", "ADVISORY"}
VALID_GATE_EFFECTS = {"FAIL", "REVIEW", "NONE"}

# This is the single ownership map used when connecting policy definitions to
# pipeline stages. A rule's evaluator determines its owner, not its old H/S/D
# prefix.
EVALUATOR_OWNERS = {
    "deterministic": "rule_engine",
    "reference_lookup": "context_engine",
    "semantic_heuristic": "ai_advisory",
    "llm_advisory": "ai_advisory",
}


class RuleCatalogueError(ValueError):
    """Raised when the rule catalogue cannot safely be used."""


def _validate_rule(rule: Any, index: int, seen_ids: set[str]) -> None:
    if not isinstance(rule, dict):
        raise RuleCatalogueError(f"Rule at index {index} must be an object.")

    missing = sorted(REQUIRED_RULE_FIELDS - rule.keys())
    if missing:
        raise RuleCatalogueError(
            f"Rule at index {index} is missing required field(s): {', '.join(missing)}."
        )

    rule_id = rule["id"]
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise RuleCatalogueError(f"Rule at index {index} has an invalid id.")
    if rule_id in seen_ids:
        raise RuleCatalogueError(f"Duplicate rule id: {rule_id}.")
    seen_ids.add(rule_id)

    if rule["evaluator"] not in VALID_EVALUATORS:
        raise RuleCatalogueError(
            f"Rule {rule_id} has unsupported evaluator {rule['evaluator']!r}."
        )
    if rule["severity"] not in VALID_SEVERITIES:
        raise RuleCatalogueError(
            f"Rule {rule_id} has unsupported severity {rule['severity']!r}."
        )
    if rule["gate_effect"] not in VALID_GATE_EFFECTS:
        raise RuleCatalogueError(
            f"Rule {rule_id} has unsupported gate effect {rule['gate_effect']!r}."
        )
    if not isinstance(rule["message"], str) or not rule["message"].strip():
        raise RuleCatalogueError(f"Rule {rule_id} must have a non-empty message.")
    if "field" not in rule and "fields" not in rule:
        raise RuleCatalogueError(f"Rule {rule_id} must define field or fields.")


def load_rule_catalogue(path: Path | str = DEFAULT_CATALOGUE_PATH) -> dict[str, Any]:
    """Return a validated rule catalogue from *path*.

    The result is intentionally not cached: tests and policy-management tools
    can update a catalogue and reload it in the same process.
    """
    catalogue_path = Path(path)
    try:
        with catalogue_path.open(encoding="utf-8") as file:
            catalogue = json.load(file)
    except FileNotFoundError as exc:
        raise RuleCatalogueError(
            f"Rule catalogue was not found: {catalogue_path}."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuleCatalogueError(
            f"Rule catalogue is not valid JSON: {catalogue_path}: {exc.msg}."
        ) from exc

    if not isinstance(catalogue, dict):
        raise RuleCatalogueError("Rule catalogue root must be an object.")
    if not catalogue.get("schema_version"):
        raise RuleCatalogueError("Rule catalogue must define schema_version.")
    rules = catalogue.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleCatalogueError("Rule catalogue must contain a non-empty rules list.")

    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        _validate_rule(rule, index, seen_ids)
    return catalogue


def rules_for_engine(engine_name: str, catalogue: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return policy definitions owned by a named pipeline stage."""
    active_catalogue = catalogue if catalogue is not None else load_rule_catalogue()
    return [
        rule
        for rule in active_catalogue["rules"]
        if EVALUATOR_OWNERS[rule["evaluator"]] == engine_name
    ]
