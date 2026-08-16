# ECN Checker Prototype — Version 1

A standalone Python prototype that validates Engineering Change Notice (ECN)
change lines against simulated master part and released Bill of Materials (BOM)
data.

## Purpose

The prototype demonstrates ECN checks before an ECN is submitted, approved,
implemented, or completed.

This Version 1 prototype does not require Windchill access. It uses CSV files
and PDF/email intake sources to simulate data that may later be retrieved from
Windchill, a PLM, or an ERP.

## Architecture

All validation is handled in pure Python — no Java required.

```text
ECN CSV + Master BOM CSV + Part Master CSV
                ↓
     Python validation rules (ecn_checker.py)
                ↓
      JSON dashboard results
                ↓
      Python assistant (LLM or fallback)
                ↓
      Reviewer summary + next actions
```

## Web Upload UI

ECN Creators and BOM Coordinators can validate their CSV files through a
browser interface before submission.

### Start the server

```bash
pip install flask
python scripts/app.py
```

Then open **http://localhost:5000** in your browser.

### How to use it

1. Select your role — **ECN Creator** (for `ecn_header` / `ecn_changes` files)
   or **BOM Coordinator** (for `bom` / `parts` files).
2. Drag-and-drop or click to browse and select one or more `.csv` files.
3. Click **Check My Files**.
4. Review per-file errors and warnings inline — fix any issues and re-upload.

## Command-line workflow

Run the full pipeline with:

```bash
python scripts/run_hybrid.py
```

This will:
- run the Python validation rules against the CSV files in `data/`,
- generate the reviewer dashboard,
- produce a structured AI summary JSON file,
- and create a simple hybrid HTML view.

Outputs are written to `out/`.

Context Engine (Stage 4) also materializes testable context data under
`out/context_engine/`:

- `parts_master_database.csv`
- `ecn_conflict_log.csv` (appends new run entries every test execution)
- `bom_structure_records.csv` (appends new run entries every test execution)

## AI usage

The workflow includes an optional AI-assisted summary step:

- `ecn_checker.py` is the deterministic rules engine.
- The Python assistant generates reviewer-friendly summaries and next actions
  from the checker output.
- If no model is configured, the system falls back to deterministic guidance.

### Optional LLM configuration

Prefer storing keys in a local `.env` file and keeping it out of Git.

```bash
copy .env.example .env
```

Then fill in the keys in `.env`:

```dotenv
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini

GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash
```

The app automatically reads `.env` from the repo root at startup.

**Manual environment variables:**

```bash
export OPENAI_API_KEY=your_key
export OPENAI_MODEL=gpt-4o-mini
```

If no credentials are configured, the assistant uses the built-in
deterministic fallback.

## Key locations

| Path | Description |
|---|---|
| `scripts/app.py` | Flask web server — upload UI and validation endpoint |
| `scripts/ecn_checker.py` | Core validation rule engine |
| `scripts/run_hybrid.py` | End-to-end CLI pipeline |
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