# ECN Checker Test Scenarios — Version 1

## Prototype validation workflow

The prototype is evaluated using sample ECN submissions across the main intake channels:

- PDF and HTML ECN form intake
- email-based ECN text export
- form-generated ECN text
- upload-based BOM / part master CSV and Excel files
- CSV ECN exports with Windchill-style column names
- legacy `.xls` conversion to `.xlsx` without importing `xlrd`

- MBOM table extraction from PDF


Each scenario validates the same downstream flow:

1. extract ECN fields from the source
2. normalise the payload into the common packet format
3. run the rule engine for structural and completeness issues
4. run AI advisory for vague or contradictory description checks
5. run context checks against lifecycle data
6. generate a reviewer summary and recommended decision

## Stage 1 intake regression scenarios

`tests/test_intake.py` includes integration-style regression coverage for the
checked-in Windchill source documents under `data/`:

| Source | Role and loader behavior | Expected result |
|---|---|---|
| `ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html` | ECN; standalone HTML table fields are normalized into the ECN header schema | ECN `4078575`; all required header fields present |
| `4078575-MBOM_xlsx.pdf` | BOM; PDF tables are normalized using the MBOM column aliases | Four sequential `ADD` rows, parts `567953`–`567956` |
| `4078575-MBOM_xlsx.pdf` | ECN; same PDF dispatched through the ECN PDF-form loader | A header dictionary, confirming PDF dispatch is role-aware |
| temporary CSV fixture | ECN; `ecnId`, `title`, `description`, and `reasonForChange` are mapped to canonical header fields | Required-field validation passes |
| temporary CSV fixture | BOM; common `lineNumber`, `Part_Number`, `Qty`, `UOM`, and `ParentPartNumber` columns are normalized | Canonical BOM row fields are populated |


The end-to-end intake scenario runs `run_intake()` with the HTML ECN and PDF
BOM, then verifies there are no missing required ECN fields, four BOM rows, and
both source paths in the packet. CSV tests exercise ECN and BOM intake through
the same `load_file()` seam, while the `.xls` test verifies conversion is
selected before the `openpyxl` loader and does not require `xlrd`. Tests also
reject unsupported `load_file()` roles. These document-based tests depend on
the corresponding files remaining in `data/`.


## Rule catalogue regression scenarios

`tests/test_rule_catalogue.py` validates the policy registry and its active
rule-engine evaluator mapping. It verifies that `docs/rules_list.json` is valid,
contains every ID in `docs/rules_origin.txt`, rejects duplicate IDs and unknown
evaluators, and maps each policy rule to its intended pipeline stage. This
ensures a policy-file edit cannot silently create an ambiguous or unowned rule.

Active deterministic catalogue entries are dispatched by the rule-engine
registry. These tests prove catalogue integrity and evaluator ownership; they
do not claim that planned `H`, `S`, or `D` rules are enforced in a pipeline run. See
[the architecture implementation-status note](architecture.md#implementation-status)
and [the rule schema](rules_schema.md) for the migration contract.

## Node 3 semantic advisory test matrix

The policy catalogue assigns S01–S05 to AI Advisory. The advisory prompt is
built from the active catalogue definitions and runtime findings use canonical
S rule IDs; legacy A rule IDs are not emitted.

| Policy rule | Semantic expectation | Test focus |
|---|---|---|
| S01 | Description semantically aligns to BOM change intent | LLM rule; fallback reports `NOT_EVALUATED` |
| S02 | Parts mentioned in description appear in BOM rows | Flag description-only parts not present in BOM |
| S03 | Description verbs align with BOM task/action | Flag contradiction between "replace/add/remove" language and BOM action |
| S04 | Products affected align with BOM parent assemblies | Flag mismatch between `affected_parts` and BOM parent assembly fields |
| S05 | Part description starts with naming noun | LLM rule; fallback reports `NOT_EVALUATED` |


### AI response integrity scenarios

A model assessment must be supported by itemised flags. The advisory normaliser
adds `AI_RESPONSE_INCOMPLETE` and marks the response `INCOMPLETE` when a model
returns `MEDIUM`/`HIGH` risk or `VAGUE`/`CONTRADICTING` quality with no flags,
or returns an invalid flags shape. A `LOW` / `CLEAR` response with an empty list
remains complete. Dashboard tests also verify that an unsupported non-clear
assessment is never shown as “No AI flags.”

Coverage is implemented in `tests/test_ai_advisory.py`,
`tests/test_dashboard_ai_advisory.py`, and pipeline-level validation is covered
in `tests/test_run_hybrid_pipeline.py`.

## Legacy checker fixture isolation

`tests/test_python_checker.py` retains isolated, temporary fixtures for the
separate legacy CSV checker. They are created by the test and are not checked
into `data/`, which is reserved for active hybrid-pipeline inputs and reference
data.



## Review summary and dashboard expectations

The reviewer-facing dashboard should show:

- blocker issues first, then warnings
- affected part numbers and change actions
- a recommended status such as PASS / WARNING / BLOCKER
- a short summary explaining why the ECN was accepted, routed back for correction, or rejected

## Limitations and recommendations

The prototype intentionally focuses on a controlled, rule-based validation layer rather than a full PLM integration. Current limitations include:

- PDF extraction depends on clean, text-based layouts and may require OCR or form-specific parsing for messy scans; BOM PDF table extraction is currently tailored to the supplied MBOM header structure

- email intake works best when standard ECN fields are labelled explicitly
- AI advisory is advisory only and must not replace human review
- ECN Conflict Log is not available in the current implementation


Recommendations for the next phase:

- standardise ECN templates across email, PDF and web forms
- add OCR support for scanned PDFs and handwritten forms
- connect the intake layer to a controlled parts source
- track reviewer decisions and feedback in a structured workflow record

## Weekly stand-up notes

Typical stand-up questions for the prototype review:

- What intake source was tested this week (email, PDF, form, or upload)?
- What fields were successfully extracted and what still needs manual intervention?
- Did the rule engine or AI advisory identify any new false positives or misses?
- Are there any blockers in the parts master or lifecycle data?
- What is the priority for the next iteration: extraction quality, rule coverage, or reviewer UI clarity?