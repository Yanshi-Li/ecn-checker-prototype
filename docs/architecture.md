# ECN Checker — Architecture

## Prototype workflow scope

The prototype is designed to handle a mix of intake sources commonly seen in ECN and BOM workflows:

- email-based ECN submissions (.eml / plain-text messages)
- form-style ECN text captured from a web form or internal intake template
- uploaded document files such as PDF and text exports
- CSV / Excel BOM or parts data supplied alongside the ECN

The intake layer normalises these inputs into a common ECN packet before the rule engine runs.

## Pipeline Overview

Engineer submits ECN + BOM File from email / form / upload
        │
        ▼
┌─────────────────────┐
│  Stage 1: Intake    │  Email / PDF / Form / CSV → Structured ECN Packet
└────────┬────────────┘
         │ Structured Data
         ▼
┌─────────────────────┐
│  Stage 2: Rule      │  Legacy runtime checks: R01 required fields,
│  Engine             │  R02 part-number format, R03 duplicates, R04 quantity
└────────┬────────────┘
         │ Errors Found → Real-Time Warning shown to Engineer
         ▼
┌─────────────────────┐
│  Stage 3: AI        │  ECN Description vs BOM Changes
│  Advisory           │  Vague / Contradicting Text Detection
└────────┬────────────┘  Fallback: rule-based if AI unavailable
         │ Part Numbers for Lookup
         ▼
┌─────────────────────┐
│  Stage 4: Context   │  Parts Master: Active / Obsolete / Phase-Out
│  Engine (RAG)       │  Part-master status and data checks
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 5: Dashboard │  Engineer View: validation and gate results
│  (HTML)             │  Audit package and advisory context
└────────┬────────────┘
         │ Gate decision
         ▼
┌─────────────────────┐
│  Stage 6: Email     │  FAIL → Engineer: fix and resubmit
│  Notification       │  PASS → Engineer + CE: ready for CE review
└─────────────────────┘


## Rule policy and current runtime checks

The versioned policy catalogue is [`docs/rules_list.json`](rules_list.json). It
contains 32 approved rules with stable IDs: hard rules `H01`–`H23`, semantic
rules `S01`–`S05`, and data rules `D01`–`D04`. Each definition declares its
scope, evaluator, severity, gate effect, message, and evidence inputs. The
human-readable policy source is [`docs/rules_origin.txt`](rules_origin.txt),
and the full schema and target finding contract are in
[`docs/rules_schema.md`](rules_schema.md).

`scripts/rule_catalogue.py` validates the catalogue at stage startup and maps
rules to their intended owners:

| Intended owner | Evaluators | Policy IDs |
|---|---|---|
| Rule Engine | `deterministic` | H01–H03, H06–H08, H11–H12, H14–H22 |
| Context Engine | `reference_lookup` | H09–H10, H13, D01–D04 |
| AI Advisory | `semantic_heuristic`, `llm_advisory` | H04–H05, H23, S01–S05 |

### Implementation status

The catalogue is currently a validated policy and ownership registry; it does
not yet dispatch individual catalogue checks. The running prototype therefore
continues to emit its pre-existing result identifiers and shapes:

| Runtime ID | Implemented check | Runtime severity |
|---|---|---|
| R01 | Required configured ECN fields are present | `ERROR` |
| R02 | A supplied BOM part number has exactly five or six digits | `ERROR` |
| R03 | No duplicate BOM part numbers | `WARNING` |
| R04 | BOM quantity is numeric and greater than zero | `ERROR` |

Context checks likewise emit flag types such as `DISCONTINUED_PART`,
`MISSING_SUPPLIER`, `UOM_MISMATCH`, and `HISTORICAL_CONFLICT`. The merge step
uses those legacy `ERROR` values and configured context flag types for the
current PASS/FAIL decision. The `BLOCKER`/`WARNING`/`ADVISORY` severity and
`FAIL`/`REVIEW`/`NONE` gate-effect vocabulary in the policy catalogue becomes
automatically authoritative only after the corresponding evaluators and merge
logic consume the unified finding contract.


## Key Files

| File                          | Role                          |
|-------------------------------|-------------------------------|
| `scripts/run_hybrid.py`       | Main orchestrator / CLI       |
| `scripts/stages/intake.py` | Stage 1: Parse ECN + BOM |
| `scripts/stages/rule_engine.py` | Stage 2: Deterministic rules |
| `scripts/stages/ai_advisory.py` | Stage 3: AI / fallback checks |
| `scripts/rule_catalogue.py` | Validates the rule catalogue and returns rules by intended stage owner |
| `scripts/stages/context_engine.py` | Stage 4: Parts/reference-data checks |
| `scripts/stages/dashboard.py` | Stage 5: HTML dashboard |
| `scripts/stages/email_notification.py` | Stage 6: gate-driven SendGrid email |

| `data/parts_master.csv`       | Parts status database         |
| `data/ecn_intake.csv`         | Sample ECN input              |
| `data/bom.csv`                | Sample BOM input              |

## Environment Variables

| Variable         | Purpose                                                         |
|------------------|-----------------------------------------------------------------|
| `GEMINI_API_KEY` | Enables AI Advisory (Stage 3) via Gemini OpenAI-compatible API |
| `GEMINI_MODEL`   | Optional Gemini model override (default: `gemini-2.5-flash`)   |
| `OPENAI_API_KEY` | Enables AI Advisory (Stage 3) via OpenAI API                   |
| `OPENAI_MODEL`   | Optional OpenAI model override (default: `gpt-4o-mini`)        |
| `SENDGRID_API_KEY` | Enables SendGrid notification delivery (Stage 6)              |
| `EMAIL_FROM_ADDRESS` | Verified SendGrid sender address for Stage 6 notifications   |
| `DRY_RUN` | Defaults to `true`; set explicitly false only to send email          |


## AI advisory response contract

Stage 3 stores an advisory object with `overall_risk`, `description_quality`,
`flags`, `recommendation`, `ai_available`, and `response_status`. A provider may
return an empty `flags` list only for a `LOW` / `CLEAR` assessment. If a provider
returns `MEDIUM` or `HIGH` risk, or `VAGUE` or `CONTRADICTING` quality, without
supporting flags, the checker adds an `AI_RESPONSE_INCOMPLETE` advisory flag and
sets `response_status` to `INCOMPLETE`. This is advisory only; it makes the
missing evidence visible and requires manual review rather than silently showing
“No AI flags.”

## Key design decisions

- ECN Conflict Log is not available in the current implementation.





