# AGENTS.md

## Project snapshot
- This repository is a prototype ECN checker that validates Engineering Change Notice data against sample CSV data for parts, BOMs, and ECN headers/changes.
- The main entry point for the end-to-end workflow is [scripts/run_hybrid.py](scripts/run_hybrid.py), which generates dashboard and AI summary outputs under [out/](out/).

## Working conventions
- Prefer small, focused changes that preserve the existing CSV-driven workflow.
- Keep validation logic, output structure, and rule IDs consistent across scripts and tests.
- When changing rules or behavior, update the relevant docs in [docs/](docs/) and add or adjust tests in [tests/](tests/).

## Common commands
- From the repository root, run the full workflow with:
  - `python scripts/run_hybrid.py`
  - or on Windows: `py scripts/run_hybrid.py`
- Run tests with:
  - `pytest -q`

## Key locations
- [scripts/](scripts/) contains the workflow and checker scripts.
- [data/](data/) contains the sample CSV inputs used by the prototype.
- [docs/](docs/) holds architecture, rule, and test documentation.
- [tests/](tests/) contains the regression tests for the checker and intake pipeline.

## Notes for agents
- Use the existing documentation in [README.md](README.md) and [docs/](docs/) as the source of truth before introducing new conventions.
- Avoid duplicating documentation; link to the existing docs when adding guidance.
- Avoid py file with similar function in different folders.