"""
Core validation logic for uploaded ECN / BOM CSV files.
Mirrors the rules applied in run_hybrid.py but operates on in-memory content
so the web upload endpoint can reuse it without touching the filesystem.
"""

from __future__ import annotations
import csv
import io
import re
from typing import Any

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_checks(
    file_data: dict[str, str],
    role: str = "ecn_creator",
) -> list[dict[str, Any]]:
    """
    Validate a dict of {filename: csv_text} and return per-file results.

    Parameters
    ----------
    file_data : dict
        Mapping of original filename → decoded CSV text.
    role : str
        'ecn_creator' or 'bom_coordinator' – controls which rule sets fire.

    Returns
    -------
    list of dicts  [{"file": str, "issues": [{"rule", "severity", "message"}]}]
    """
    # ── Build a parts lookup for cross-file checks ───────────────────────────
    # Key: part_number (lowercase), Value: True = active, False = obsolete/inactive
    parts_active: dict[str, bool] = {}
    for filename, content in file_data.items():
        if _detect_file_type(filename, content) == "parts":
            reader = _make_reader(content)
            rows = list(reader)
            if len(rows) > 1:
                col = _col_map(rows[0])
                for row in rows[1:]:
                    pn = _val(row, col, "part_number").strip().lower()
                    # Support both column naming conventions used across CSV files
                    status = (
                        _val(row, col, "lifecyclestatus").strip().upper()
                        or _val(row, col, "status").strip().upper()
                    )
                    if pn:
                        parts_active[pn] = status not in (
                            "OBSOLETE", "INACTIVE", "END-OF-LIFE"
                        )

    results = []
    for filename, content in file_data.items():
        issues: list[dict[str, str]] = []
        file_type = _detect_file_type(filename, content)

        reader = _make_reader(content)
        rows = list(reader)
        headers = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []

        # ── Universal checks ─────────────────────────────────────────────────
        issues += _check_not_empty(filename, rows)
        issues += _check_no_duplicate_headers(filename, headers)
        issues += _check_no_blank_rows(filename, data_rows)

        # ── File-type checks ─────────────────────────────────────────────────
        if file_type == "ecn_header":
            issues += _check_ecn_header(filename, headers, data_rows)
        elif file_type == "ecn_changes":
            issues += _check_ecn_changes(filename, headers, data_rows)
            if parts_active:
                issues += _check_new_part_active(filename, headers, data_rows, parts_active)
        elif file_type == "bom":
            issues += _check_bom(filename, headers, data_rows)
        elif file_type == "parts":
            issues += _check_parts(filename, headers, data_rows)
        else:
            issues.append(
                _issue(
                    "FILE001",
                    "warning",
                    f"Could not determine file type for '{filename}'. "
                    "Expected filename to contain ecn_header, ecn_changes, bom, or parts.",
                )
            )

        results.append({"file": filename, "file_type": file_type, "issues": issues})

    return results


# ---------------------------------------------------------------------------
# File-type detection
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, str] = {
    "ecn_header": "ecn_header",
    "ecn_changes": "ecn_changes",
    "ecn_change": "ecn_changes",
    "bom": "bom",
    "parts": "parts",
}


def _detect_file_type(filename: str, content: str) -> str:
    lower = filename.lower()
    for keyword, ftype in _TYPE_KEYWORDS.items():
        if keyword in lower:
            return ftype

    # Fallback: sniff headers
    reader = _make_reader(content)
    rows = list(reader)
    if not rows:
        return "unknown"
    headers = {h.strip().lower() for h in rows[0]}

    if {"ecn_number", "title", "status"} <= headers:
        return "ecn_header"
    if {"ecn_number", "part_number", "change_type"} <= headers:
        return "ecn_changes"
    if {"part_number", "quantity", "parent_part"} <= headers:
        return "bom"
    if {"part_number", "description", "unit_of_measure"} <= headers:
        return "parts"

    return "unknown"


# ---------------------------------------------------------------------------
# Universal checks
# ---------------------------------------------------------------------------

def _check_not_empty(filename: str, rows: list) -> list:
    if not rows:
        return [_issue("GEN001", "error", "File is empty.")]
    if len(rows) == 1:
        return [_issue("GEN002", "warning", "File contains a header row but no data rows.")]
    return []


def _check_no_duplicate_headers(filename: str, headers: list) -> list:
    seen, dupes = set(), set()
    for h in headers:
        h_norm = h.strip().lower()
        if h_norm in seen:
            dupes.add(h.strip())
        seen.add(h_norm)
    if dupes:
        return [_issue("GEN003", "error", f"Duplicate column headers: {', '.join(sorted(dupes))}.")]
    return []


def _check_no_blank_rows(filename: str, data_rows: list) -> list:
    issues = []
    for i, row in enumerate(data_rows, start=2):
        if all(cell.strip() == "" for cell in row):
            issues.append(_issue("GEN004", "warning", f"Row {i} is completely blank."))
    return issues


# ---------------------------------------------------------------------------
# ECN Header checks  (rules ECN-H-*)
# ---------------------------------------------------------------------------

_REQUIRED_ECN_HEADER_COLS = [
    "ecn_number", "title", "status", "initiator", "date_initiated",
]

_VALID_STATUSES = {"draft", "pending", "approved", "rejected", "released"}

_ECN_NUMBER_RE = re.compile(r"^ECN-\d{4,}$", re.IGNORECASE)


def _check_ecn_header(filename: str, headers: list, data_rows: list) -> list:
    issues = []
    col = _col_map(headers)

    # Required columns
    issues += _require_columns(col, _REQUIRED_ECN_HEADER_COLS, "ECN-H-001")

    for i, row in enumerate(data_rows, start=2):

        ecn_num = _val(row, col, "ecn_number")
        if ecn_num and not _ECN_NUMBER_RE.match(ecn_num):
            issues.append(
                _issue("ECN-H-002", "error",
                       f"Row {i}: ecn_number '{ecn_num}' does not match pattern ECN-NNNN.")
            )

        status = _val(row, col, "status").lower()
        if status and status not in _VALID_STATUSES:
            issues.append(
                _issue("ECN-H-003", "error",
                       f"Row {i}: status '{status}' is not one of {sorted(_VALID_STATUSES)}.")
            )

        date_str = _val(row, col, "date_initiated")
        if date_str and not _is_iso_date(date_str):
            issues.append(
                _issue("ECN-H-004", "warning",
                       f"Row {i}: date_initiated '{date_str}' is not in YYYY-MM-DD format.")
            )

        if not _val(row, col, "initiator"):
            issues.append(
                _issue("ECN-H-005", "error", f"Row {i}: initiator is required and cannot be blank.")
            )

    return issues


# ---------------------------------------------------------------------------
# ECN Changes checks  (rules ECN-C-*)
# ---------------------------------------------------------------------------

_REQUIRED_ECN_CHANGES_COLS = [
    "ecn_number", "part_number", "change_type", "old_value", "new_value",
]

_VALID_CHANGE_TYPES = {"add", "remove", "modify", "replace"}


def _check_ecn_changes(filename: str, headers: list, data_rows: list) -> list:
    issues = []
    col = _col_map(headers)

    issues += _require_columns(col, _REQUIRED_ECN_CHANGES_COLS, "ECN-C-001")

    for i, row in enumerate(data_rows, start=2):

        ecn_num = _val(row, col, "ecn_number")
        if ecn_num and not _ECN_NUMBER_RE.match(ecn_num):
            issues.append(
                _issue("ECN-C-002", "error",
                       f"Row {i}: ecn_number '{ecn_num}' does not match pattern ECN-NNNN.")
            )

        ct = _val(row, col, "change_type").lower()
        if ct and ct not in _VALID_CHANGE_TYPES:
            issues.append(
                _issue("ECN-C-003", "error",
                       f"Row {i}: change_type '{ct}' must be one of {sorted(_VALID_CHANGE_TYPES)}.")
            )

        if not _val(row, col, "part_number"):
            issues.append(
                _issue("ECN-C-004", "error", f"Row {i}: part_number is required.")
            )

        old_val = _val(row, col, "old_value")
        new_val = _val(row, col, "new_value")
        if ct == "modify" and old_val and new_val and old_val.strip() == new_val.strip():
            issues.append(
                _issue("ECN-C-005", "warning",
                       f"Row {i}: old_value and new_value are identical for a 'modify' change.")
            )

    return issues


# ---------------------------------------------------------------------------
# ECN Changes → Parts cross-file check  (rule ECN-C-006)
# ---------------------------------------------------------------------------

def _check_new_part_active(
    filename: str,
    headers: list,
    data_rows: list,
    parts_active: dict[str, bool],
) -> list:
    """
    ECN-C-006: For every REPLACE or ADD row in ecn_changes, verify that
    newPartNumber (or new_value) exists in the parts master and is not obsolete/inactive.
    Fires only when a parts-master file was also supplied in the same run_checks call.
    """
    issues = []
    col = _col_map(headers)

    # Support both column naming conventions
    new_part_col = "newpartnumber" if "newpartnumber" in col else "new_value"
    change_type_col = "change_type" if "change_type" in col else "action"

    for i, row in enumerate(data_rows, start=2):
        ct = _val(row, col, change_type_col).strip().lower()
        if ct not in ("replace", "add"):
            continue

        new_pn = _val(row, col, new_part_col).strip()
        if not new_pn:
            continue

        key = new_pn.lower()
        if key not in parts_active:
            issues.append(
                _issue(
                    "ECN-C-006", "error",
                    f"Row {i}: newPartNumber '{new_pn}' not found in parts master.",
                )
            )
        elif not parts_active[key]:
            issues.append(
                _issue(
                    "ECN-C-006", "error",
                    f"Row {i}: newPartNumber '{new_pn}' is OBSOLETE or INACTIVE "
                    "and cannot be used as a replacement.",
                )
            )

    return issues


# ---------------------------------------------------------------------------
# BOM checks  (rules BOM-*)
# ---------------------------------------------------------------------------

_REQUIRED_BOM_COLS = ["part_number", "parent_part", "quantity", "unit_of_measure"]

_VALID_UOM = {"ea", "each", "ft", "m", "kg", "lb", "in", "mm", "cm", "l", "ml", "lot"}


def _check_bom(filename: str, headers: list, data_rows: list) -> list:
    issues = []
    col = _col_map(headers)

    issues += _require_columns(col, _REQUIRED_BOM_COLS, "BOM-001")

    for i, row in enumerate(data_rows, start=2):

        qty_str = _val(row, col, "quantity")
        if qty_str:
            try:
                qty = float(qty_str)
                if qty <= 0:
                    issues.append(
                        _issue("BOM-002", "error",
                               f"Row {i}: quantity must be greater than zero (got {qty_str}).")
                    )
            except ValueError:
                issues.append(
                    _issue("BOM-003", "error",
                           f"Row {i}: quantity '{qty_str}' is not a valid number.")
                )

        uom = _val(row, col, "unit_of_measure").lower()
        if uom and uom not in _VALID_UOM:
            issues.append(
                _issue("BOM-004", "warning",
                       f"Row {i}: unit_of_measure '{uom}' is not in the recognised list "
                       f"{sorted(_VALID_UOM)}.")
            )

        pn = _val(row, col, "part_number")
        parent = _val(row, col, "parent_part")
        if pn and parent and pn.strip().lower() == parent.strip().lower():
            issues.append(
                _issue("BOM-005", "error",
                       f"Row {i}: part_number and parent_part are the same (circular reference).")
            )

    return issues


# ---------------------------------------------------------------------------
# Parts master checks  (rules PRT-*)
# ---------------------------------------------------------------------------

_REQUIRED_PARTS_COLS = ["part_number", "description", "unit_of_measure"]


def _check_parts(filename: str, headers: list, data_rows: list) -> list:
    issues = []
    col = _col_map(headers)

    issues += _require_columns(col, _REQUIRED_PARTS_COLS, "PRT-001")

    seen_pns: set[str] = set()
    for i, row in enumerate(data_rows, start=2):

        pn = _val(row, col, "part_number").strip()
        if not pn:
            issues.append(
                _issue("PRT-002", "error", f"Row {i}: part_number is required.")
            )
            continue

        if pn.lower() in seen_pns:
            issues.append(
                _issue("PRT-003", "error", f"Row {i}: duplicate part_number '{pn}'.")
            )
        seen_pns.add(pn.lower())

        desc = _val(row, col, "description")
        if not desc.strip():
            issues.append(
                _issue("PRT-004", "warning", f"Row {i}: description is blank for part '{pn}'.")
            )

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader(content: str):
    return csv.reader(io.StringIO(content))


def _col_map(headers: list) -> dict[str, int]:
    """Return lowercase-stripped header → column index."""
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def _val(row: list, col: dict[str, int], key: str) -> str:
    idx = col.get(key)
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _require_columns(col: dict, required: list[str], rule_id: str) -> list:
    missing = [c for c in required if c not in col]
    if missing:
        return [
            _issue(rule_id, "error",
                   f"Missing required column(s): {', '.join(missing)}.")
        ]
    return []


def _is_iso_date(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value.strip()))


def _issue(rule: str, severity: str, message: str) -> dict[str, str]:
    return {"rule": rule, "severity": severity, "message": message}


def run_checker(data_dir: str | "os.PathLike[str]", output_dir: str | "os.PathLike[str]" | None = None) -> dict[str, Any]:
    """Run the checker against a directory of ECN CSV samples and write the dashboard JSON."""
    import json
    from os import PathLike
    from pathlib import Path

    data_path = Path(data_dir)
    out_path = Path(output_dir) if output_dir is not None else data_path
    out_path.mkdir(parents=True, exist_ok=True)

    file_data: dict[str, str] = {}
    for csv_name in ["ecn_header.csv", "ecn_changes.csv", "parts_master.csv", "bom.csv"]:
        csv_path = data_path / csv_name
        if csv_path.exists():
            file_data[csv_name] = csv_path.read_text(encoding="utf-8")

    results = run_checks(file_data)
    header_rows = list(csv.DictReader(io.StringIO(file_data.get("ecn_header.csv", "")))) if "ecn_header.csv" in file_data else []
    change_rows = list(csv.DictReader(io.StringIO(file_data.get("ecn_changes.csv", "")))) if "ecn_changes.csv" in file_data else []

    parts_lookup: dict[str, str] = {}
    if "parts_master.csv" in file_data:
        for row in csv.DictReader(io.StringIO(file_data["parts_master.csv"])):
            pn = (row.get("partNumber") or row.get("part_number") or "").strip()
            if pn:
                parts_lookup[pn.lower()] = pn

    dashboard_rows: list[dict[str, Any]] = []
    for row in header_rows:
        ecn_id = (row.get("ecnId") or row.get("ecn_number") or "").strip()
        if not ecn_id:
            continue

        blocker_count = 0
        warning_count = 0

        description = (row.get("description") or "").strip()
        if not description:
            warning_count += 1
        if "<script>" in description.lower():
            blocker_count += 1

        effective_date = (row.get("effectiveDate") or row.get("date_initiated") or "").strip()
        if not effective_date:
            warning_count += 1
        elif not re.match(r"^\d{4}-\d{2}-\d{2}$", effective_date):
            warning_count += 1

        title = (row.get("title") or "").strip()
        if not title or len(title.split()) < 2:
            blocker_count += 1

        status = (row.get("status") or "").strip().lower()
        if status and status not in {"draft", "pending", "approved", "rejected", "released"}:
            warning_count += 1

        for change_row in change_rows:
            change_ecn = (change_row.get("ecnId") or change_row.get("ecn_number") or "").strip()
            if change_ecn != ecn_id:
                continue

            action = (change_row.get("action") or change_row.get("change_type") or "").strip().lower()
            if action not in {"add", "remove", "modify", "replace", "change_quantity"}:
                blocker_count += 1

            new_part = (change_row.get("newPartNumber") or change_row.get("new_value") or change_row.get("Part_Number") or "").strip()
            if action in {"add", "replace"} and not new_part:
                blocker_count += 1

            qty_raw = (change_row.get("newQuantity") or change_row.get("new_value") or change_row.get("quantity") or "").strip()
            if qty_raw:
                try:
                    qty = float(qty_raw)
                    if qty <= 0:
                        blocker_count += 1
                except ValueError:
                    blocker_count += 1

            if new_part and new_part.lower() not in parts_lookup and action in {"add", "replace"}:
                blocker_count += 1

            if action == "remove" and not (change_row.get("oldPartNumber") or change_row.get("old_value")):
                blocker_count += 1

        if blocker_count > 0:
            decision = "BLOCKER"
        elif warning_count > 0:
            decision = "WARNING"
        else:
            decision = "PASS"

        dashboard_rows.append({
            "ecnId": ecn_id,
            "title": title,
            "status": row.get("status") or "DRAFT",
            "blockerCount": blocker_count,
            "warningCount": warning_count,
            "decision": decision,
        })

    payload = {"ecns": dashboard_rows, "generatedBy": "ecn_checker.run_checker"}
    json_path = out_path / "ecn-dashboard.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload