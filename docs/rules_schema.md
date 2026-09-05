# ECN Checker Rule System Schema

## Purpose

This document defines the contract used to create, execute, report, test, and maintain ECN validation rules. It intentionally does **not** contain the active rule catalogue. Active rule definitions must be maintained in a versioned machine-readable configuration file; this document defines the common schema that those definitions and all engines must follow.

The schema separates a rule's business purpose from the engine that evaluates it and from its workflow outcome. A rule may therefore be evaluated deterministically, using reference data, or with AI assistance without changing its identity or reporting format.

> **Current implementation status:** the catalogue is validated and its rules are mapped to intended pipeline-stage owners. The existing prototype still runs legacy evaluator functions and emits legacy finding shapes and IDs. The unified finding contract in this document is the required target for catalogue-driven evaluator migration; it is not yet the runtime output contract for every stage. See [architecture.md](architecture.md#implementation-status).


## Core principles

- A rule has one stable canonical ID for its full lifecycle.
- Rule category, evaluator, severity, and gate effect are independent properties.
- Intake normalizes source documents and CSV columns into canonical packet fields before any rule is evaluated.
- Every evaluator returns the same finding contract.
- AI-derived conclusions are evidence-backed and reviewable; they do not silently become deterministic facts.
- A rule change is versioned, reviewed, and regression-tested before release.

## Rule definition contract

The active catalogue is `docs/rules_list.json`. Every rule definition in that file uses the following fields.

| Field | Required | Description |
|---|---:|---|
| `id` | Yes | Stable rule identifier. Existing `H`, `S`, and `D` IDs are retained for compatibility. |
| `domain` | Yes | Business domain: `ECN_HEADER`, `CHANGE_DESCRIPTION`, `IMPLEMENTATION`, `BOM_LINE`, `PART_MASTER`, `COMPLIANCE`, or `SEMANTIC_ALIGNMENT`. |
| `scope` | Yes | Evaluation granularity: `ecn`, `bom_line`, `part`, `assembly`, or `description_to_bom`. |
| `evaluator` | Yes | Evaluation method: `deterministic`, `reference_lookup`, `semantic_heuristic`, or `llm_advisory`. |
| `check` | Yes | Stable name of the reusable validation capability. |
| `field` or `fields` | Yes | Canonical packet field or fields consumed by the check. |
| `severity` | Yes | User-facing importance when the check fails. |
| `gate_effect` | Yes | Workflow effect when the check fails. |
| `message` | Yes | User-facing failure message. |
| `applies_when` | No | Condition that determines whether the rule applies. Omit it when the rule is unconditional. |
| `parameters` | No | Check-specific thresholds, controlled values, or matching options. |
| `reference` or `references` | No | Reference data required by a lookup check. |
| `lookup_key` | No | Packet field used to look up the reference record. |
| `implementation_note` | No | Constraint or ambiguity that must be resolved before implementation. |

## Allowed outcome values

| Property | Values | Meaning |
|---|---|---|
| `severity` | `BLOCKER`, `WARNING`, `ADVISORY` | Importance shown to users. |
| `gate_effect` | `FAIL`, `REVIEW`, `NONE` | Effect on ECN workflow. |
| `evaluation_status` | `PASS`, `FAIL`, `SKIPPED`, `NOT_EVALUATED`, `ERROR` | Result of running a rule. |

`BLOCKER` normally uses `gate_effect: FAIL`; `WARNING` normally uses `REVIEW`; and `ADVISORY` normally uses `NONE`. The explicit `gate_effect` is authoritative so an approved exception can be modelled without redefining severity.

## Rule configuration shape

```json docs/rules_list.json
{
  "schema_version": "1.0.0",
  "catalogue_name": "ECN Checker Rules",
  "source": "docs/rules_origin.txt",
  "rules": [
    {
      "id": "H01",
      "domain": "ECN_HEADER",
      "scope": "ecn",
      "evaluator": "deterministic",
      "check": "required",
      "field": "header.name_of_change",
      "severity": "BLOCKER",
      "gate_effect": "FAIL",
      "message": "Name of Change is blank, mandatory field missing"
    }
  ]
}
```

## Canonical ECN packet

Rules must use normalized fields, not source-specific CSV headings or PDF labels. The intake stage owns mapping source fields to the canonical model.

| Area | Canonical fields |
|---|---|
| ECN header | `header.change_notice_number`, `header.name_of_change`, `header.description_of_change`, `header.products_affected`, `header.change_type` |
| Implementation | `header.implementation.site`, `header.implementation.date`, `header.implementation.person` |
| BOM line | `bom[].line_number`, `bom[].action`, `bom[].quantity`, `bom[].unit_of_measure`, `bom[].task_number` |
| Parent assembly | `bom[].parent.part_number`, `bom[].parent.description` |
| Existing child | `bom[].existing_child.part_number`, `bom[].existing_child.description` |
| New child | `bom[].new_child.part_number`, `bom[].new_child.description` |
| Reference data | `reference.parts`, `reference.current_bom`, `reference.approvals`, `reference.ecn_history` |

## Evaluator responsibilities

| Evaluator | Responsibility | Output requirements |
|---|---|---|
| `deterministic` | Checks formats, required values, dependencies, controlled values, dates, quantities, and duplicate records. | Exact expected and actual values. |
| `reference_lookup` | Checks current BOM, part master, lifecycle, supplier, UoM, approvals, and history. | Dataset identity, lookup key, and matched or missing record evidence. |
| `semantic_heuristic` | Uses controlled vocabularies and deterministic extraction to compare text with BOM facts. | Extracted parts, actions, and comparison evidence. |
| `llm_advisory` | Assesses ambiguity, clarity, or contextual interpretation after normalized facts are supplied. | Source excerpts, affected lines, confidence, and `review_required: true`. |
| `manual_review` | Creates a deliberate review task where automation cannot make a reliable decision. | Review reason and required approver role. |

`manual_review` is part of the target evaluator model. It is not accepted by the current `scripts/rule_catalogue.py` validator until a corresponding stage owner and evaluator implementation are introduced.


## Unified finding contract

Catalogue-driven evaluators must append findings using this common structure. Engine-specific fields may be placed inside `evidence`; they must not replace the common fields. Legacy prototype outputs remain temporarily supported until each evaluator migrates.

```json
{
  "finding_id": "unique-finding-id",
  "rule_id": "DOMAIN-001",
  "rule_version": "1.0.0",
  "evaluation_status": "FAIL",
  "severity": "BLOCKER",
  "gate_effect": "FAIL",
  "source_engine": "rule_engine",
  "scope": "bom_line",
  "location": { "line_number": 1, "field": "bom.quantity" },
  "message_code": "STABLE_MESSAGE_CODE",
  "message": "User-facing message.",
  "expected": "Expected condition",
  "actual": "Observed value",
  "evidence": {},
  "remediation": "Corrective action.",
  "confidence": 1.0,
  "review_required": false
}
```

## AI and semantic policy

AI is an advisory evaluator, not the source of record. It may identify ambiguity, explain a semantic mismatch, or recommend review. An AI finding must include the description excerpt, applicable normalized BOM facts, its confidence, and a clear recommendation. It must set `review_required: true`.

A workflow failure based solely on an AI response is not permitted. A gate-closing decision must be supported by a deterministic rule, a reference-data rule, or an approved manual-review policy.

## Rule lifecycle and change control

1. Define the business requirement and required evidence.
2. Assign a stable ID and choose the appropriate evaluator.
3. Specify the validation check, applicable fields, optional applicability condition, severity, gate effect, and message.
4. Add pass, fail, and not-applicable test cases.
5. Review the rule with the ECN process owner and affected data owner.
6. Release the changed catalogue version with compatible reporting aliases where required.
7. Deprecate, rather than reuse, IDs that are superseded.

## Testing requirements

Each active rule requires automated tests that verify:

- a passing case;
- a failing case with the expected finding fields and evidence;
- a skipped case when the applicability condition is false;
- reference-data behavior where applicable; and
- AI/semantic evidence and fallback behavior where applicable.

Dashboards, emails, gate logic, and audit exports must consume the unified finding contract rather than evaluator-specific result formats.

## Ownership

- **Process owner:** owns business policy, severity, and gate effect.
- **Data owner:** owns reference-data meaning, quality, and availability.
- **Engineering owner:** owns schema compatibility, evaluator implementation, tests, and release.
- **Quality or compliance owner:** owns approval and waiver policy for regulated or safety-related rules.

See `docs/architecture.md` for pipeline responsibilities and `docs/test-scenarios.md` for test-scenario guidance.