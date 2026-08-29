# ECN Checker Test Scenarios — Version 1

## Prototype validation workflow

The prototype is evaluated using sample ECN submissions across the main intake channels:

- PDF and HTML ECN form intake
- email-based ECN text export
- form-generated ECN text
- upload-based BOM / part master CSV and Excel files
- MBOM table extraction from PDF


Each scenario validates the same downstream flow:

1. extract ECN fields from the source
2. normalise the payload into the common packet format
3. run the rule engine for structural and completeness issues
4. run AI advisory for vague or contradictory description checks
5. run context checks against lifecycle / historical ECN data
6. generate a reviewer summary and recommended decision

## Stage 1 intake regression scenarios

`tests/test_intake.py` includes integration-style regression coverage for the
checked-in Windchill source documents under `data/`:

| Source | Role and loader behavior | Expected result |
|---|---|---|
| `ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html` | ECN; standalone HTML table fields are normalized into the ECN header schema | ECN `4078575`; all required header fields present |
| `4078575-MBOM_xlsx.pdf` | BOM; PDF tables are normalized using the MBOM column aliases | Four sequential `ADD` rows, parts `567953`–`567956` |
| `4078575-MBOM_xlsx.pdf` | ECN; same PDF dispatched through the ECN PDF-form loader | A header dictionary, confirming PDF dispatch is role-aware |

The end-to-end intake scenario runs `run_intake()` with the HTML ECN and PDF
BOM, then verifies there are no missing required ECN fields, four BOM rows, and
both source paths in the packet. Tests also reject unsupported `load_file()`
roles. These document-based tests depend on the corresponding files remaining
in `data/`.

## Node 3 semantic advisory test matrix


The AI advisory stage now tracks the semantic checks defined in the ECN intake mapping:

| Rule | Semantic expectation | Test focus |
|---|---|---|
| A01 | Description semantically aligns to BOM change intent | Flag missing BOM context when BOM parts are not described |
| A02 | Parts mentioned in description appear in BOM rows | Flag description-only parts not present in BOM |
| A03 | Description verbs align with BOM task/action | Flag contradiction between "replace/add/remove" language and BOM action |
| A04 | Products affected align with BOM parent assemblies | Flag mismatch between `affected_parts` and BOM parent assembly fields |
| A05 | Part description starts with naming noun | Flag part descriptions that start with action verbs (for example "Replace ...") |

Coverage is implemented in [test_ai_advisory.py](C:/Users/liy/FPA-Internship/repo/ecn-checker-prototype.worktrees/ai-advisory-module-testing/tests/test_ai_advisory.py) and pipeline-level validation is covered in [test_run_hybrid_pipeline.py](C:/Users/liy/FPA-Internship/repo/ecn-checker-prototype.worktrees/ai-advisory-module-testing/tests/test_run_hybrid_pipeline.py).

## Initial failure scenario

The supplied `ecn_changes.csv` intentionally includes invalid data.

| Line | ECN action | Test scenario | Expected result |
|---:|---|---|---|
| 1 | REPLACE | Replace active C-200 with obsolete C-250 | PART-004 Blocker |
| 2 | REMOVE | Remove C-999, which is not in released BOM | BOM-001 Blocker |
| 3 | ADD | Add C-100, which already exists in BOM | BOM-002 Warning |
| 3 | ADD | Add safety-critical C-100 without Quality approval | REG-001 Warning |
| 4 | CHANGE_QUANTITY | Change C-300 quantity from 4 to 0 | BOM-003 Blocker |
| 5 | ADD | Add active C-400 with quantity 2 | Pass |

Expected final decision:

```text
FINAL DECISION: ECN cannot proceed.
```

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
- historical conflict checks are limited to the sample history data and do not yet cover full enterprise lifecycle records

Recommendations for the next phase:

- standardise ECN templates across email, PDF and web forms
- add OCR support for scanned PDFs and handwritten forms
- connect the intake layer to a controlled parts and ECN history source
- track reviewer decisions and feedback in a structured workflow record

## Weekly stand-up notes

Typical stand-up questions for the prototype review:

- What intake source was tested this week (email, PDF, form, or upload)?
- What fields were successfully extracted and what still needs manual intervention?
- Did the rule engine or AI advisory identify any new false positives or misses?
- Are there any blockers in the parts master, lifecycle data, or conflict logic?
- What is the priority for the next iteration: extraction quality, rule coverage, or reviewer UI clarity?