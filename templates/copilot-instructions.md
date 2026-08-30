# GitHub Copilot Instructions for ecn-checker-prototype

## Project Context
This repository processes, validates, and generates workflow reports for Engineering Change Notices (ECNs) against a Bill of Materials (BOM) database. It consists of Python intake, validation, AI assistance, and dashboard generation modules.

## File & Path Conventions
- **Data Folder:** Input CSV files live in `data/`.
  - Core data files: `master_bom.csv` (or `bom.csv`), `ecn_header.csv` (or `ecn_headers.csv`), `ecn_changes.csv`, and `parts_master.csv`.
- **Output Folder:** Generated JSON and HTML dashboards must be saved in `out/`.
- Always resolve paths relative to the project root using `pathlib.Path(__file__).resolve().parent`.

## Coding Standards & Python Conventions
- **Python Version:** Compatible with Python 3.10+.
- **Formatting:** Use 4-space indentation for all block scopes. Avoid tab characters.
- **Type Annotations:** Provide explicit type hints for function arguments and return types (`Dict[str, Any]`, `List[Dict[str, Any]]`, `Path`, etc.).
- **String Formatting:** Prefer standard f-strings for string formatting.
- **HTML Outputs:** When concatenating inline HTML strings in Python scripts, wrap dynamic content with `html.escape()` to sanitize strings.

## Business Logic & Validation Rules
- **ECN Severity Levels:** Categorize validation findings strictly into `BLOCKER`, `WARNING`, or `PASS`.
- **Decision Outcomes:** High-level ECN decisions should be `BLOCK`, `REVIEW`, or `APPROVE`.
- **Description Rule:** ECN descriptions must be between 10 and 250 characters and contain allowed special characters. Use `ecn_checker.check_description_issues(ecn)` for validation.
- **BOM Rules:** - `REMOVE`, `REPLACE`, and `CHANGE_QUANTITY` actions must verify that `oldPartNumber` exists in `master_bom.csv` with a `RELEASED` status under `affectedAssembly`.

## Debugging & Error Handling
- Use defensive `.get()` calls when parsing ECN dictionary payloads.
- Raise clear `FileNotFoundError` or standard Python exceptions when required CSVs or dashboard files are missing.