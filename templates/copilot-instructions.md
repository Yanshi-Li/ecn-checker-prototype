# GitHub Copilot Instructions for ecn-checker-prototype

## Project Context
This repository processes, validates, and generates workflow reports for Engineering Change Notices (ECNs) against a Bill of Materials (BOM) database. It consists of Python intake, validation, AI assistance, and dashboard generation modules.

## File & Path Conventions
- **Data Folder:** Active hybrid-pipeline inputs and reference CSV files live in `data/`: `ecn_intake.csv`, `bom.csv`, `Part_Master.csv`, and `ecn_history.csv`. The context engine reads `Part_Master.csv` directly and must not generate a parts-master copy.
- **Output Folder:** Generated dashboard, summary, and context artifacts are saved in `out/`.

- Always resolve paths relative to the project root using `pathlib.Path(__file__).resolve().parent`.

## Coding Standards & Python Conventions
- **Python Version:** Compatible with Python 3.10+.
- **Formatting:** Use 4-space indentation for all block scopes. Avoid tab characters.
- **Type Annotations:** Provide explicit type hints for function arguments and return types (`Dict[str, Any]`, `List[Dict[str, Any]]`, `Path`, etc.).
- **String Formatting:** Prefer standard f-strings for string formatting.
- **HTML Outputs:** When concatenating inline HTML strings in Python scripts, wrap dynamic content with `html.escape()` to sanitize strings.

## Business Logic & Validation Rules
- **Policy source:** Use `docs/rules_list.json` and `docs/rules_schema.md` for rule IDs, canonical fields, severities, and gate effects.
- **Runtime behavior:** Keep changes compatible with the active hybrid pipeline. The policy catalogue is not yet a complete runtime-rule dispatcher; see `docs/architecture.md` for implemented checks.
- **Canonical ECN identifier:** External input uses `Change Notice Number`, normalized to `header.change_notice_number`.


## Debugging & Error Handling
- Use defensive `.get()` calls when parsing ECN dictionary payloads.
- Raise clear `FileNotFoundError` or standard Python exceptions when required CSVs or dashboard files are missing.