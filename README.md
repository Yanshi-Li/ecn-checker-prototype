# ECN Checker

## Overview

ECN Checker is a prototype for ECN creators, BOM coordinators, reviewers, and administrators. It ingests an Engineering Change Notice (ECN) and a Bill of Materials (BOM), validates them with deterministic rules and part-master context, adds an AI-assisted (or rule-based fallback) review, makes a gate decision, presents the findings, and records evaluation data.

The **React frontend is the supported browser interface for every role and workflow**. Flask provides the backend for authentication, intake, validation, persistence, and notifications. Batch testing remains available through the command-line runner; it is not a browser workflow.


## Architecture

The end-to-end CLI pipeline is implemented by `scripts/run_hybrid.py`; the current stage implementations live in `scripts/stages/` (with compatibility wrappers in `scripts/`).

1. **Intake** — parses the required ECN and optional single BOM, adds source-file metadata, and normalizes them into one packet.
2. **Rule Engine** — applies the currently implemented deterministic checks for required ECN fields, part-number format, duplicate BOM lines, and quantity.
3. **AI Advisory** — reviews catalogue-defined semantic rules S01–S05 using OpenAI first, retries with Gemini when OpenAI fails and Gemini is configured, and otherwise evaluates S02–S04 heuristically while reporting LLM-owned S01/S05 as `NOT_EVALUATED`. Legacy A rule IDs are not emitted.
4. **Context Engine** — checks BOM parts directly against `data/Part_Master.csv` and writes audit artifacts under `out/context_engine/`; it does not generate a parts-master copy.
5. **Merge Step / Gate Decision** — combines findings into a `PASS` or `FAIL`; rule errors and selected part issues close the gate, while warnings and AI notes remain advisory.
6. **Results and user interface** — the CLI produces `out/dashboard.html` and `out/ai_summary.md`; React provides the interactive browser interface for testers, reviewers, and administrators.

7. **Email Notification** — sends or dry-runs a gate-specific notification through SendGrid.

### Rule policy catalogue

`docs/rules_list.json` is the versioned machine-readable policy catalogue. It retains the business-rule IDs `H01`–`H23`, `S01`–`S05`, and `D01`–`D04`, and assigns each rule to a deterministic, reference-data, semantic-heuristic, or LLM-advisory evaluator. `scripts/rule_catalogue.py` validates that file and provides the ownership mapping used by the pipeline stages.

The catalogue is the policy and migration source of truth; `docs/rules_origin.txt` preserves its approved human-readable source. Active entries (`runtime_status: "active"`) are dispatched through registered stage evaluators and emit the unified finding contract. The incremental migration currently activates H01, H03, H11, H12, and H24; explicitly planned entries are not runtime checks. The part-number format check is now canonical H24 and is selected from the catalogue like the other deterministic checks.

See [docs/architecture.md](docs/architecture.md) for the workflow, [docs/rules_schema.md](docs/rules_schema.md) for the rule contract, and [docs/rules_origin.txt](docs/rules_origin.txt) for the readable policy table.


## Supported file formats

| Submission role | Supported extensions | Handling |
|---|---|---|
| ECN | `.csv`, `.xlsx`, `.xls`, `.pdf`, `.html`, `.htm`, `.eml` | CSV/Excel use the first row as the header; PDF forms, HTML forms, and email bodies are parsed into ECN header fields. |
| BOM | `.csv`, `.xlsx`, `.xls`, `.pdf` | CSV/Excel produce row dictionaries; template-style Excel and PDF MBOM data are normalized to BOM rows. Legacy `.xls` files are converted to temporary `.xlsx` files before intake. |

Legacy `.xls` intake requires an approved local converter: LibreOffice (`soffice`) or Microsoft Excel on Windows. The converted file is temporary and is removed after loading; the submitted source file is not modified.

## Primary interface: React

The React + TypeScript frontend is the supported interface for testers, reviewers, and administrators. It uses the Flask backend for authentication, pre-checks, evaluation records, reviewer workflows, and notifications. See the [React frontend README](frontend/README.md) for current local setup instructions.

React supports tester sign-in and pre-checks, reviewer queues and judgements, administrator management and reporting, and evaluation records. Testers can upload files or enter ECN details and BOM rows manually; both modes use the same Flask validation and persistence workflow. Run batch testing through `scripts/run_batch.py`; batch testing is intentionally not part of the browser UI.






## Command-line workflow
PDF routing is role-aware: an ECN PDF is parsed as fields, while a BOM PDF is parsed as MBOM tables. PDF BOM extraction looks for a table header containing **Part Number** and **Action**, then maps recognized columns such as description, quantity, unit, action, and source. The checked-in HTML ECN and MBOM PDF examples in `data/` have regression coverage.

Batch testing is command-line only. Run `py scripts/run_batch.py --help` for options; for example, use `py scripts/run_batch.py --ecn-dir "path/to/ecn_completed" --bom-dir "path/to/boms"` to match and execute cases from directories.

## Setup — local

1. Clone the repository and enter it.

   ```bash
   git clone <repository-url>
   cd ECN-Checker
   ```

2. Create and activate a virtual environment.

      ```bash
   python -m venv .venv
   # Windows, if `python` is not on PATH: py -m venv .venv
   # Windows PowerShell: .venv\Scripts\Activate.ps1
   # macOS/Linux: source .venv/bin/activate
   ```

3. Install the project dependencies.

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env`, then replace placeholder values with approved credentials as needed. Keep `.env` out of source control.

   ```bash
   copy .env.example .env
   ```

   On macOS/Linux, use `cp .env.example .env`. An LLM key is optional because the pipeline falls back to rule-based advisory checks. SendGrid settings are only needed for live email delivery.

5. Run the CLI pipeline. Provide the ECN explicitly; BOM input is optional. Repeat `--bom` up to four times to process each ECN/BOM pair separately.

      ```bash
      python scripts/run_hybrid.py --ecn "data/ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html"
   python scripts/run_hybrid.py --ecn "data/ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html" --bom data/4078575-MBOM_xlsx.pdf --engineer-email engineer@example.com --ce-email chief.engineer@example.com
   # Process two BOMs as two independent comparisons:
   python scripts/run_hybrid.py --ecn "path/to/submission.eml" --bom "path/to/12345-MBOM.xlsx" --bom "path/to/12345-EBOM.xlsx"
   # Windows, if `python` is not on PATH: py scripts/run_hybrid.py --ecn path/to/submission.eml
   ```

   The CLI accepts `--ecn`, `--bom`, `--engineer-email`, and `--ce-email`. `DRY_RUN` is an environment/secret setting, not a CLI option. CLI output includes `out/dashboard.html`, `out/ai_summary.md`, and context-engine CSV artifacts.

6. Initialise the local evaluation tables. This command prompts for the database password without storing it in the repository.

   ```powershell
   py scripts/initialise_evaluation_db.py
   ```

7. Run the React interface locally. Follow the two-process instructions in the [React frontend README](frontend/README.md): start Flask from the repository root, then start the Vite development server from `frontend/`. Open the Vite URL (normally `http://localhost:5173`).


### Dependencies

`requirements.txt` currently installs the backend and CLI dependencies: `pandas`, `openpyxl`, `pdfplumber`, `httpx`, `openai`, `sendgrid`, `psycopg[binary]`, and `pytest` (for the test suite).

## Deployment direction

The deployment should serve the React frontend and Flask backend together (or through an approved web server/reverse proxy), with PostgreSQL accessible only to the backend. See [Internal Deployment Architecture](docs/deployment-architecture.md) for the proposed deployment shape.


## Environment variables / secrets

For local use, the AI advisory and Flask backend read environment variables; the AI advisory also loads a repository-root `.env` file, with process environment values taking precedence. Do not commit real credentials.


| Variable | Purpose | Used by | Example/default |
|---|---|---|---|
| `GEMINI_API_KEY` | Enables Gemini AI advisory when OpenAI is unavailable or fails. | CLI and Flask | `your-gemini-api-key` |
| `GEMINI_MODEL` | Gemini model override. | CLI and Flask | `gemini-2.5-flash` |
| `GEMINI_BASE_URL` | Gemini OpenAI-compatible API endpoint override. | CLI and Flask | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `OPENAI_API_KEY` | Enables OpenAI-compatible AI advisory; preferred when both AI keys are set. | CLI and Flask | `your-openai-api-key` |
| `OPENAI_MODEL` | OpenAI model override. | CLI and Flask | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint override. | CLI and Flask | `https://gateway.aitools.corp.fisherpaykel.com` |
| `SENDGRID_API_KEY` | Authorizes SendGrid delivery. Required only when live email is enabled. | CLI and Flask | `your-sendgrid-api-key` |
| `EMAIL_FROM_ADDRESS` | Verified SendGrid sender address. Required only when live email is enabled. | CLI and Flask | `verified-sender@example.com` |
| `DRY_RUN` | Controls whether notifications are only logged rather than sent. | CLI and Flask | `true` (default); set `false`, `0`, `no`, or `off` to enable delivery |
| `ECN_DB_HOST` | Local evaluation database host. | Evaluation store | `localhost` |
| `ECN_DB_PORT` | Local evaluation database port. | Evaluation store | `5432` |
| `ECN_DB_NAME` | Evaluation database name. | Evaluation store | `ecn_prechecker_evaluation` |
| `ECN_DB_USER` | Restricted evaluation database role. | Evaluation store | `ecn_app` |
| `ECN_DB_PASSWORD` | Password for the evaluation database role. | Evaluation store | No default; keep it out of source control |
| `REVIEWER_ADMIN_EMAIL` | Bootstrap administrator email for the reviewer area. | Flask login bootstrap | No default |
| `REVIEWER_ADMIN_PASSWORD` | Bootstrap administrator password; used only to create the first administrator. | Flask login bootstrap | No default; keep it out of source control |

Reviewer and administrator workflows are available through React and protected Flask endpoints. Configure bootstrap values as required, initialise the schema, and never commit passwords. Reviewer passwords are stored as salted PBKDF2 hashes, and a reviewer can only open assigned attempts.



## Running tests

```bash
python -m pytest -q
# Windows, if `python` is not on PATH: py -m pytest -q
```

The backend suite covers intake (including sample HTML ECN and PDF MBOM extraction), the validated rule catalogue and stage ownership mapping, deterministic rules, AI fallback/configuration, part-master checks, merge/gate behavior, notification rendering, evaluation persistence, reviewer/admin operations, the hybrid pipeline, and the legacy CSV checker. React behavior tests cover tester pre-check and independent judgement flows; run them from `frontend/` with `npm test`.

## Email notifications

Node **6a** is the `FAIL` path: it notifies only the engineer with blockers and part issues so the ECN can be fixed and resubmitted. Node **6b** is the `PASS` path: it notifies the engineer and Chief Engineer that the ECN is ready for CE review, including advisory warnings and AI notes. `DRY_RUN` defaults to `true`, so no email is sent unless it is explicitly disabled and valid SendGrid credentials plus a verified sender address are configured.

## Known limitations / TODO

- Intake is template- and label-driven. ECN PDF parsing relies on known field labels; HTML parsing is designed for label/value tables (including the checked-in Windchill export); and email parsing expects recognizable labels such as ECN ID, Title, Description, and Change Type.
- PDF BOM extraction only recognizes extractable tables with MBOM-like **Part Number** and **Action** headers. Scanned PDFs and differently structured tables may yield no rows or need a parser enhancement.
- Each comparison intentionally accepts at most one BOM. The CLI can repeat `--bom` up to four times, but processes each BOM independently and writes suffixed dashboard/summary artifacts for multi-BOM runs. A BOM filename containing a different ECN number is retained as a non-gating warning asking the user to check the filename.
- AI review is advisory only and includes all normalized BOM lines in the model prompt. OpenAI is attempted first; if it fails and Gemini is configured, Gemini is attempted before the catalogue-driven fallback evaluates S02–S04 and marks S01/S05 `NOT_EVALUATED`.
- The gate does not fail for every context warning. It closes for rule findings with `gate_effect == "FAIL"`, `DISCONTINUED_PART`, `MISSING_SUPPLIER`, and `UOM_MISMATCH`; source filename warnings, other context flags, rule warnings, and AI findings are advisory.
- BOM structure records append on each run under `out/context_engine/`; clean or manage these generated artifacts as appropriate for repeatable local work.
- ECN Conflict Log is not available in the current implementation.
- This remains a CSV/reference-data prototype: it does not connect directly to Windchill, PLM, or ERP systems.

## Key locations

| Path | Description |
|---|---|
| `scripts/app.py` | Flask web server — upload UI and validation endpoint |
| `scripts/ecn_checker.py` | Core validation rule engine |
| `scripts/run_hybrid.py` | End-to-end CLI pipeline |
| `scripts/stages/validation_notification.py` | Validation report email builder and SMTP sender |
| `frontend/` | React browser interface for testers, reviewers, and administrators |

| `data/` | Sample CSV inputs used by the prototype |
| `out/` | Generated dashboard and AI summary outputs |
| `docs/` | Architecture, rule, and test documentation |
| `tests/` | Regression tests |

### Repository structure (clean layout)

```text
scripts/    # pipeline stages and orchestration code
data/       # sample ECN/BOM/parts/history input files
tests/      # regression and module tests
docs/       # architecture/rules/test scenario docs
templates/  # web UI templates
out/        # generated outputs (ignored in git)
```

## Running tests

```bash
pytest -q
```
| `scripts/run_hybrid.py` | CLI orchestration of all stages and notifications |
| `scripts/stages/` | Intake, rule, AI, context, merge, dashboard, and email stage implementations |

| `data/` | Sample ECN/BOM inputs and parts master |
| `docs/` | Architecture, rule-policy, deployment, and intake-test documentation |
| `tests/` | Regression and pipeline tests |
| `out/` | Generated CLI dashboard, summary, and context artifacts |

## Documentation

- [Architecture and current runtime behavior](docs/architecture.md)
- [Rule-system schema and finding contract](docs/rules_schema.md)
- [Approved rule-policy source table](docs/rules_origin.txt)
- [Machine-readable rule catalogue](docs/rules_list.json)
- [React frontend setup and workflows](frontend/README.md)


- [Tester introduction and test procedure](docs/tester-guide.md)
- [One-hour laptop test session](docs/laptop-test-session-guide.md)
- [Intake scenarios and regression expectations](docs/test-scenarios.md)


