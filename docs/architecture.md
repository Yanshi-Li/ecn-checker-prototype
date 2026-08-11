# ECN Checker — Architecture

## Pipeline Overview

Engineer submits ECN + BOM File
        │
        ▼
┌─────────────────────┐
│  Stage 1: Intake    │  CSV / Excel / PDF → Structured ECN Packet
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
│  Engine (RAG)       │  Historical ECN Conflict Check
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 5: Dashboard │  Engineer View: Fix Errors in Real-Time
│  (HTML)             │  BOM Coordinator View: Full Audit Package
└────────┬────────────┘
         │ Audit Package Ready
         ▼
┌─────────────────────┐
│  Stage 6: BOM       │  APPROVE → ECN Released + Email
│  Coordinator        │  REJECT  → ECN to Draft + Feedback Email
└─────────────────────┘

## Rule IDs

| ID  | Description                        | Severity |
|-----|------------------------------------|----------|
| R01 | Required fields present            | ERROR    |
| R02 | Part number format valid           | ERROR    |
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
| `scripts/context_engine.py`   | Stage 4: Parts + history RAG  |
| `scripts/dashboard.py`        | Stage 5: HTML dashboard       |
| `scripts/approval_workflow.py`| Stage 6: Approve/reject/email |
| `data/parts_master.csv`       | Parts status database         |
| `data/ecn_history.csv`        | Historical ECN records        |
| `data/ecn_intake.csv`         | Sample ECN input              |
| `data/bom.csv`                | Sample BOM input              |

## Environment Variables

| Variable        | Purpose                            |
|-----------------|------------------------------------|
| `OPENAI_API_KEY`| Enables AI Advisory (Stage 3)      |

## Running

