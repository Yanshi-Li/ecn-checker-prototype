# ECN Checker

## Overview

ECN Checker is a Python prototype for ECN creators, BOM coordinators, and Chief Engineers. It ingests an Engineering Change Notice (ECN) and a Bill of Materials (BOM), validates them with deterministic rules and part-master context, adds an AI-assisted (or rule-based fallback) review, makes a gate decision, presents the findings, and notifies the appropriate reviewers by email.

## Architecture

The end-to-end CLI pipeline is implemented by `scripts/run_hybrid.py`; the current stage implementations live in `scripts/stages/` (with compatibility wrappers in `scripts/`).

1. **Intake** — parses the submitted ECN and BOM and normalizes them into one packet.
2. **Rule Engine** — applies deterministic checks for required ECN fields, part-number format, duplicate BOM lines, quantity, change type, and date format.
3. **AI Advisory** — reviews ECN/BOM semantics using Gemini or OpenAI when configured; otherwise it uses deterministic advisory heuristics.
4. **Context Engine** — checks BOM parts against `data/parts_master.csv` and writes context artifacts under `out/context_engine/`.
5. **Merge Step / Gate Decision** — combines findings into a `PASS` or `FAIL`; rule errors and selected part issues close the gate, while warnings and AI notes remain advisory.
6. **Dashboard** — the CLI produces `out/dashboard.html` and `out/ai_summary.md`; the Streamlit app renders the gate findings directly.
7. **Email Notification** — sends or dry-runs a gate-specific notification through SendGrid.

See [docs/architecture.md](docs/architecture.md) for the workflow and rule reference. The README reflects the current code where it differs from that document.

## Supported file formats

| Submission role | Supported extensions | Handling |
|---|---|---|
| ECN | `.csv`, `.xlsx`, `.xls`, `.pdf`, `.html`, `.htm`, `.eml` | CSV/Excel use the first row as the header; PDF forms, HTML forms, and email bodies are parsed into ECN header fields. |
| BOM | `.csv`, `.xlsx`, `.xls`, `.pdf` | CSV/Excel produce row dictionaries; template-style Excel and PDF MBOM data are normalized to BOM rows. |

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

5. Run the CLI pipeline. Defaults are `data/ecn_intake.csv` and `data/bom.csv`.

      ```bash
   python scripts/run_hybrid.py
   python scripts/run_hybrid.py --ecn "data/ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html" --bom data/4078575-MBOM_xlsx.pdf --engineer-email engineer@example.com --ce-email chief.engineer@example.com
   # Windows, if `python` is not on PATH: py scripts/run_hybrid.py
   ```

   The CLI accepts `--ecn`, `--bom`, `--engineer-email`, and `--ce-email`. `DRY_RUN` is an environment/secret setting, not a CLI option. CLI output includes `out/dashboard.html`, `out/ai_summary.md`, and context-engine CSV artifacts.

6. Run the Streamlit interface locally.

   ```bash
   streamlit run streamlit_app.py
   # Windows, if `streamlit` is not on PATH: py -m streamlit run streamlit_app.py
   ```

   Upload one ECN and one BOM, select **Run Checks**, then use the separate notification control if appropriate. The Streamlit page does not generate the CLI HTML dashboard or summary file.

### Dependencies

`requirements.txt` currently installs: `streamlit`, `pandas`, `openpyxl`, `pdfplumber`, `httpx`, `openai`, `sendgrid`, and `pytest` (for the test suite).

## Setup — Streamlit Cloud deployment

Push the repository to GitHub, create an app at [Streamlit Community Cloud](https://share.streamlit.io/), select the repository and branch, and set `streamlit_app.py` as the entry point. Add the real secrets in the app dashboard under **Settings → Secrets** rather than committing them; Community Cloud installs `requirements.txt` automatically. Keep `DRY_RUN=true` until live delivery is approved. Before enabling SendGrid, verify the sender domain/address used by `EMAIL_FROM_ADDRESS` (domain authentication is the intended production setup; single-sender verification is suitable for limited testing). See [docs/streamlit-deploy.md](docs/streamlit-deploy.md) for the complete deployment steps.

## Environment variables / secrets

For local CLI use, the AI advisory reads a repository-root `.env` file; process environment values take precedence. In Streamlit, configured secrets are read first. Do not commit real credentials.

| Variable | Purpose | Used by | Example/default |
|---|---|---|---|
| `GEMINI_API_KEY` | Enables Gemini AI advisory; preferred when both AI keys are set. | CLI and Streamlit | `your-gemini-api-key` |
| `GEMINI_MODEL` | Gemini model override. | CLI and Streamlit | `gemini-2.5-flash` |
| `GEMINI_BASE_URL` | Gemini OpenAI-compatible API endpoint override. | CLI and Streamlit | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `OPENAI_API_KEY` | Enables OpenAI-compatible AI advisory when no Gemini key is configured. | CLI and Streamlit | `your-openai-api-key` |
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

The test suite covers intake (including sample HTML ECN and PDF MBOM extraction), deterministic rules, AI fallback/configuration, part-master checks, merge/gate behavior, Node 6 notification rendering, the hybrid pipeline, and the legacy CSV checker.

## Email notifications

Node **6a** is the `FAIL` path: it notifies only the engineer with blockers and part issues so the ECN can be fixed and resubmitted. Node **6b** is the `PASS` path: it notifies the engineer and Chief Engineer that the ECN is ready for CE review, including advisory warnings and AI notes. `DRY_RUN` defaults to `true`, so no email is sent unless it is explicitly disabled and valid SendGrid credentials plus a verified sender address are configured.

## Known limitations / TODO

- Intake is template- and label-driven. ECN PDF parsing relies on known field labels; HTML parsing is designed for label/value tables (including the checked-in Windchill export); and email parsing expects recognizable labels such as ECN ID, Title, Description, and Change Type.
- PDF BOM extraction only recognizes extractable tables with MBOM-like **Part Number** and **Action** headers. Scanned PDFs and differently structured tables may yield no rows or need a parser enhancement.
- The Streamlit uploader currently offers every intake extension for both upload controls, even though HTML is ECN-only and BOM parsing is supported only for CSV, Excel, and PDF. The low-level loader also accepts `.eml` for the BOM role but returns an ECN-style dictionary, which results in an empty BOM rather than a valid BOM import.
- AI review is advisory only and is limited to the first 20 BOM lines sent to the model. If no usable provider/key is available, the rule-based fallback is used.
- The gate does not fail for every context warning. It closes for rule-engine `ERROR`s, `DISCONTINUED_PART`, `MISSING_SUPPLIER`, and `UOM_MISMATCH`; other context flags, rule warnings, and AI findings are advisory.
- BOM structure records append on each run under `out/context_engine/`; clean or manage these generated artifacts as appropriate for repeatable local work.
- ECN Conflict Log is not available in the current implementation.
- This remains a CSV/reference-data prototype: it does not connect directly to Windchill, PLM, or ERP systems.

## Key locations

| Path | Description |
|---|---|
| `scripts/run_hybrid.py` | CLI orchestration of all stages and notifications |
| `scripts/stages/` | Intake, rule, AI, context, merge, dashboard, and email stage implementations |
| `streamlit_app.py` | Streamlit upload, gate-results, and explicit notification interface |
| `data/` | Sample ECN/BOM inputs and parts master |
| `docs/` | Architecture, deployment, rule, and intake-test documentation |
| `tests/` | Regression and pipeline tests |
| `out/` | Generated CLI dashboard, summary, and context artifacts |

## Documentation

- [Architecture and rules](docs/architecture.md)
- [Streamlit Cloud deployment](docs/streamlit-deploy.md)
- [Intake scenarios and regression expectations](docs/test-scenarios.md)
- [Rule catalogue](docs/rule-catalogue.md)