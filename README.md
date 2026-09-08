# ECN Checker

## Overview

ECN Checker is a Python prototype for ECN creators, BOM coordinators, and Chief Engineers. It ingests an Engineering Change Notice (ECN) and a Bill of Materials (BOM), validates them with deterministic rules and part-master context, adds an AI-assisted (or rule-based fallback) review, makes a gate decision, presents the findings, and notifies the appropriate reviewers by email.

## Architecture

The end-to-end CLI pipeline is implemented by `scripts/run_hybrid.py`; the current stage implementations live in `scripts/stages/` (with compatibility wrappers in `scripts/`).

1. **Intake** — parses the required ECN and optional single BOM, adds source-file metadata, and normalizes them into one packet.
2. **Rule Engine** — applies the currently implemented deterministic checks for required ECN fields, part-number format, duplicate BOM lines, and quantity.
3. **AI Advisory** — reviews catalogue-defined semantic rules S01–S05 using OpenAI first, retries with Gemini when OpenAI fails and Gemini is configured, and otherwise evaluates S02–S04 heuristically while reporting LLM-owned S01/S05 as `NOT_EVALUATED`. Legacy A rule IDs are not emitted.
4. **Context Engine** — checks BOM parts directly against `data/Part_Master.csv` and writes audit artifacts under `out/context_engine/`; it does not generate a parts-master copy.
5. **Merge Step / Gate Decision** — combines findings into a `PASS` or `FAIL`; rule errors and selected part issues close the gate, while warnings and AI notes remain advisory.
6. **Dashboard** — the CLI produces `out/dashboard.html` and `out/ai_summary.md`; the Streamlit app renders the gate findings directly.
7. **Email Notification** — sends or dry-runs a gate-specific notification through SendGrid.

### Rule policy catalogue

`docs/rules_list.json` is the versioned machine-readable policy catalogue. It retains the business-rule IDs `H01`–`H23`, `S01`–`S05`, and `D01`–`D04`, and assigns each rule to a deterministic, reference-data, semantic-heuristic, or LLM-advisory evaluator. `scripts/rule_catalogue.py` validates that file and provides the ownership mapping used by the pipeline stages.

The catalogue is the policy and migration source of truth; `docs/rules_origin.txt` preserves its approved human-readable source. Active entries (`runtime_status: "active"`) are dispatched through registered stage evaluators and emit the unified finding contract. The incremental migration currently activates H01, H03, H11, and H12; explicitly planned entries are not runtime checks. R02 remains a clearly marked compatibility check because it has no catalogue policy entry.

See [docs/architecture.md](docs/architecture.md) for the workflow, [docs/rules_schema.md](docs/rules_schema.md) for the rule contract, and [docs/rules_origin.txt](docs/rules_origin.txt) for the readable policy table.


## Supported file formats

| Submission role | Supported extensions | Handling |
|---|---|---|
| ECN | `.csv`, `.xlsx`, `.xls`, `.pdf`, `.html`, `.htm`, `.eml` | CSV/Excel use the first row as the header; PDF forms, HTML forms, and email bodies are parsed into ECN header fields. |
| BOM | `.csv`, `.xlsx`, `.xls`, `.pdf` | CSV/Excel produce row dictionaries; template-style Excel and PDF MBOM data are normalized to BOM rows. Legacy `.xls` files are converted to temporary `.xlsx` files before intake. |

Legacy `.xls` intake requires an approved local converter: LibreOffice (`soffice`) or Microsoft Excel on Windows. The converted file is temporary and is removed after loading; the submitted source file is not modified.

## Streamlit intake and validation reports

Run the public Streamlit interface with:

```powershell
streamlit run streamlit_app.py
```

The app supports both uploaded files and manual intake. Manual intake uses the
canonical staged intake fields: `change_notice_number`, `name_of_change`,
`reason_for_change`, `description_of_change`, `products_affected`,
`change_actions`, and `date`, plus optional intake fields and canonical BOM
rows.

After validation, the user can explicitly send a validation report to
`yanshili645@gmail.com`. The email is a report only; it does not approve or
reject an ECN. SMTP configuration is required before the button can send.
See [docs/streamlit-deploy.md](docs/streamlit-deploy.md) for deployment
configuration.

## Command-line workflow
PDF routing is role-aware: an ECN PDF is parsed as fields, while a BOM PDF is parsed as MBOM tables. PDF BOM extraction looks for a table header containing **Part Number** and **Action**, then maps recognized columns such as description, quantity, unit, action, and source. The checked-in HTML ECN and MBOM PDF examples in `data/` have regression coverage.

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

6. Run the Streamlit interface locally.

   ```bash
   streamlit run streamlit_app.py
   # Windows, if `streamlit` is not on PATH: py -m streamlit run streamlit_app.py
   ```

   Upload one required ECN and optionally one BOM, select **Run Checks**, then use the separate notification control if appropriate. To check multiple BOMs, run each ECN/BOM pair separately. The Streamlit page does not generate the CLI HTML dashboard or summary file.

### Dependencies

`requirements.txt` currently installs: `streamlit`, `pandas`, `openpyxl`, `pdfplumber`, `httpx`, `openai`, `sendgrid`, and `pytest` (for the test suite).

## Setup — Streamlit Cloud deployment

Push the repository to GitHub, create an app at [Streamlit Community Cloud](https://share.streamlit.io/), select the repository and branch, and set `streamlit_app.py` as the entry point. Add the real secrets in the app dashboard under **Settings → Secrets** rather than committing them; Community Cloud installs `requirements.txt` automatically. Keep `DRY_RUN=true` until live delivery is approved. Before enabling SendGrid, verify the sender domain/address used by `EMAIL_FROM_ADDRESS` (domain authentication is the intended production setup; single-sender verification is suitable for limited testing). See [docs/streamlit-deploy.md](docs/streamlit-deploy.md) for the complete deployment steps.

## Environment variables / secrets

For local CLI use, the AI advisory reads a repository-root `.env` file; process environment values take precedence. In Streamlit, configured secrets are read first. Do not commit real credentials.

| Variable | Purpose | Used by | Example/default |
|---|---|---|---|
| `GEMINI_API_KEY` | Enables Gemini AI advisory when OpenAI is unavailable or fails. | CLI and Streamlit | `your-gemini-api-key` |
| `GEMINI_MODEL` | Gemini model override. | CLI and Streamlit | `gemini-2.5-flash` |
| `GEMINI_BASE_URL` | Gemini OpenAI-compatible API endpoint override. | CLI and Streamlit | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `OPENAI_API_KEY` | Enables OpenAI-compatible AI advisory; preferred when both AI keys are set. | CLI and Streamlit | `your-openai-api-key` |
| `OPENAI_MODEL` | OpenAI model override. | CLI and Streamlit | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint override. | CLI and Streamlit | `https://gateway.aitools.corp.fisherpaykel.com` |
| `SENDGRID_API_KEY` | Authorizes SendGrid delivery. Required only when live email is enabled. | CLI and Streamlit | `your-sendgrid-api-key` |
| `EMAIL_FROM_ADDRESS` | Verified SendGrid sender address. Required only when live email is enabled. | CLI and Streamlit | `verified-sender@example.com` |
| `DRY_RUN` | Controls whether notifications are only logged rather than sent. | CLI and Streamlit | `true` (default); set `false`, `0`, `no`, or `off` to enable delivery |

## Running tests

```bash
python -m pytest -q
# Windows, if `python` is not on PATH: py -m pytest -q
```

The test suite covers intake (including sample HTML ECN and PDF MBOM extraction), the validated rule catalogue and stage ownership mapping, deterministic rules, AI fallback/configuration, part-master checks, merge/gate behavior, Node 6 notification rendering, the hybrid pipeline, and the legacy CSV checker.

## Email notifications

Node **6a** is the `FAIL` path: it notifies only the engineer with blockers and part issues so the ECN can be fixed and resubmitted. Node **6b** is the `PASS` path: it notifies the engineer and Chief Engineer that the ECN is ready for CE review, including advisory warnings and AI notes. `DRY_RUN` defaults to `true`, so no email is sent unless it is explicitly disabled and valid SendGrid credentials plus a verified sender address are configured.

## Known limitations / TODO

- Intake is template- and label-driven. ECN PDF parsing relies on known field labels; HTML parsing is designed for label/value tables (including the checked-in Windchill export); and email parsing expects recognizable labels such as ECN ID, Title, Description, and Change Type.
- PDF BOM extraction only recognizes extractable tables with MBOM-like **Part Number** and **Action** headers. Scanned PDFs and differently structured tables may yield no rows or need a parser enhancement.
- Each comparison intentionally accepts at most one BOM. The CLI can repeat `--bom` up to four times, but processes each BOM independently and writes suffixed dashboard/summary artifacts for multi-BOM runs. A BOM filename containing a different ECN number is retained as a non-gating warning asking the user to check the filename.
- AI review is advisory only and is limited to the first 20 BOM lines sent to the model. OpenAI is attempted first; if it fails and Gemini is configured, Gemini is attempted before the catalogue-driven fallback evaluates S02–S04 and marks S01/S05 `NOT_EVALUATED`.
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
| `streamlit_app.py` | Streamlit upload/manual intake and report UI |
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
| `streamlit_app.py` | Streamlit upload, gate-results, and explicit notification interface |
| `data/` | Sample ECN/BOM inputs and parts master |
| `docs/` | Architecture, rule-policy, deployment, and intake-test documentation |
| `tests/` | Regression and pipeline tests |
| `out/` | Generated CLI dashboard, summary, and context artifacts |

## Documentation

- [Architecture and current runtime behavior](docs/architecture.md)
- [Rule-system schema and finding contract](docs/rules_schema.md)
- [Approved rule-policy source table](docs/rules_origin.txt)
- [Machine-readable rule catalogue](docs/rules_list.json)
- [Streamlit Cloud deployment](docs/streamlit-deploy.md)
- [Intake scenarios and regression expectations](docs/test-scenarios.md)
