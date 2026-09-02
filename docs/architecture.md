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
│  Stage 2: Rule      │  R01 Required Fields  R02 Part Number Format
│  Engine             │  R03 Duplicate Lines  R04 Zero-Qty Check
└────────┬────────────┘  R05 Change Type      R06 Date Format
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


## Rule IDs

| ID  | Description                        | Severity |
|-----|------------------------------------|----------|
| R01 | Required fields present            | ERROR    |
| R02 | Part number is exactly 5 or 6 digits | ERROR    |
| R03 | No duplicate BOM lines             | WARNING  |
| R04 | No zero/negative quantity          | ERROR    |
| R05 | Change type in approved list       | WARNING  |
| R06 | Date in YYYY-MM-DD format          | WARNING  |

## Key Files

| File                          | Role                          |
|-------------------------------|-------------------------------|
| `scripts/run_hybrid.py`       | Main orchestrator / CLI       |
| `scripts/intake.py`           | Stage 1: Parse ECN + BOM      |
| `scripts/rule_engine.py`      | Stage 2: Deterministic rules  |
| `scripts/ai_advisory.py`      | Stage 3: AI / fallback checks |
| `scripts/context_engine.py`   | Stage 4: Parts RAG            |
| `scripts/dashboard.py`        | Stage 5: HTML dashboard       |
| `scripts/email_notification.py`| Stage 6: gate-driven SendGrid email |

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


## Key design decisions

- ECN Conflict Log is not available in the current implementation.





