import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from decimal import Decimal


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FOLDER = ROOT / "data"


def check_description_issues(ecn: Dict[str, Any]) -> List[str]:
    """Helper used by workflows to validate description text standalone."""
    issues = []
    desc = (ecn.get("description") or "").strip()
    if not desc:
        issues.append("Description is blank.")
        return issues
    if len(desc) < 10:
        issues.append(f"Description too short ({len(desc)} chars, min 10 required).")
    elif len(desc) > 250:
        issues.append(f"Description too long ({len(desc)} chars, max 250 allowed).")
    
    allowed_pattern = r"^[\w\s.,;:()/_+&'\"\-#%]+$"
    if not re.match(allowed_pattern, desc):
        issues.append("Description contains invalid special characters.")
    return issues


def _load_parts(path: Path) -> Dict[str, Dict[str, Any]]:
    parts: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parts[row["partNumber"]] = {
                "partNumber": row["partNumber"],
                "description": row["description"],
                "lifecycleStatus": row["lifecycleStatus"],
                "safetyCritical": row["safetyCritical"].strip().lower() == "true",
                "approvedSupplier": row["approvedSupplier"],
            }
    return parts


def _load_bom(path: Path) -> List[Dict[str, Any]]:
    bom_lines: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bom_lines.append(
                {
                    "parentPartNumber": row["parentPartNumber"],
                    "componentPartNumber": row["componentPartNumber"],
                    "quantity": Decimal(row["quantity"]),
                    "uom": row["uom"],
                    "bomRevision": row["bomRevision"],
                    "status": row["status"],
                }
            )
    return bom_lines


def _load_headers(path: Path) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            headers.append(
                {
                    "ecnId": row["ecnId"],
                    "title": row["title"],
                    "description": row["description"],
                    "status": row["status"],
                    "affectedAssembly": row["affectedAssembly"],
                    "effectiveDate": row["effectiveDate"],
                    "qualityApproval": row["qualityApproval"].strip().lower() == "true",
                }
            )
    return headers


def _load_changes(path: Path) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            changes.append(
                {
                    "ecnId": row["ecnId"],
                    "lineNumber": row["lineNumber"],
                    "action": row["action"],
                    "parentPartNumber": row["parentPartNumber"],
                    "oldPartNumber": row["oldPartNumber"],
                    "newPartNumber": row["newPartNumber"],
                    "oldQuantity": Decimal(row["oldQuantity"]),
                    "newQuantity": Decimal(row["newQuantity"]),
                    "uom": row["uom"],
                }
            )
    return changes


def _make_result(severity: str, rule_id: str, rule_description: str, message: str, evidence: str = "", reason: str = "", action: str = "") -> Dict[str, Any]:
    return {
        "severity": severity,
        "ruleId": rule_id,
        "ruleDescription": rule_description,
        "message": message,
        "evidence": evidence,
        "reason": reason,
        "requiredAction": action,
    }


def _check_ecn_description(ecn: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    description = (ecn.get("description") or "").strip()
    if not description:
        results.append(_make_result("BLOCKER", "DESC-001", "ECN description must be completed", "The ECN description is blank.", "ECN header field: description is empty.", "Checkers and approvers need a clear description to understand what is changing and why the ECN was raised.", "Enter a meaningful ECN description before submission."))
        return

    length = len(description)
    min_length = 10
    max_length = 250
    if length < min_length:
        results.append(_make_result("BLOCKER", "DESC-001", "ECN description must have a meaningful length", f"The ECN description has only {length} characters. Minimum required length is {min_length}.", f"Description value: '{description}'", "A very short description does not provide enough information for Engineering, Quality, Manufacturing, or Procurement review.", "Provide a clearer description of the proposed engineering change."))
    elif length > max_length:
        results.append(_make_result("BLOCKER", "DESC-001", "ECN description must have a meaningful length", f"The ECN description has {length} characters. Maximum allowed length is {max_length}.", f"Description length={length}, maximum={max_length}", "The description exceeds the Version 1 field limit and may not fit in connected PLM, ERP, or reporting fields.", "Shorten the description or place detailed information in an attachment."))
    else:
        results.append(_make_result("PASS", "DESC-001", "ECN description must have a meaningful length", f"The ECN description contains {length} characters.", f"Description length={length}, allowed range={min_length} to {max_length}", "The description is present and has sufficient length for initial review."))

    allowed_pattern = r"^[\w\s.,;:()/_+&'\"\-#%]+$"
    if not re.match(allowed_pattern, description):
        invalid_chars = []
        for char in description:
            if not re.match(r"[\w\s.,;:()/_+&'\"\-#%]", char):
                if char not in invalid_chars:
                    invalid_chars.append(char)
        results.append(_make_result("BLOCKER", "DESC-002", "ECN description must contain only permitted characters", "The ECN description contains unsupported character(s): " + "".join(invalid_chars), "Description value: '" + description + "'", "Unsupported characters can cause security, display, export, or integration issues.", "Remove or replace unsupported characters. Allowed characters include letters, numbers, spaces, and . , ; : ( ) / _ + & ' \" - # %"))
    else:
        results.append(_make_result("PASS", "DESC-002", "ECN description must contain only permitted characters", "The ECN description contains permitted characters only.", "Validated against Version 1 permitted-character rule.", "The description is suitable for the prototype input format."))


def _check_parent_assembly_matches_ecn(ecn: Dict[str, Any], line: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    if line["parentPartNumber"] != ecn["affectedAssembly"]:
        results.append(_make_result("BLOCKER", "ECN-003", "Each change line must use the ECN affected assembly", f"Line {line['lineNumber']}: Parent assembly {line['parentPartNumber']} does not match ECN affected assembly {ecn['affectedAssembly']}.", "", "Correct the parent assembly or create a separate ECN.", "Correct the parent assembly or create a separate ECN."))
    else:
        results.append(_make_result("PASS", "ECN-003", "Each change line must use the ECN affected assembly", f"Line {line['lineNumber']}: Parent assembly matches ECN."))


def _check_existing_part_in_released_bom(ecn: Dict[str, Any], line: Dict[str, Any], bom: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> None:
    requires_existing_part = line["action"] in {"REMOVE", "REPLACE", "CHANGE_QUANTITY"}
    if not requires_existing_part:
        return

    exists = any(
        bom_entry["parentPartNumber"] == ecn["affectedAssembly"]
        and bom_entry["componentPartNumber"] == line["oldPartNumber"]
        and bom_entry["status"] == "RELEASED"
        for bom_entry in bom
    )
    if not exists:
        results.append(_make_result("BLOCKER", "BOM-001", "Existing component must exist in the released BOM", f"Line {line['lineNumber']}: Existing component '{line['oldPartNumber']}' was not found in released BOM.", f"Searched released BOM for parent={ecn['affectedAssembly']}, component={line['oldPartNumber']}. No matching RELEASED record was found.", "An ECN cannot remove, replace, or change quantity for a component that is not in the current released BOM.", "Correct the old part number or select a component from the released BOM."))
    else:
        results.append(_make_result("PASS", "BOM-001", "Existing component must exist in the released BOM", f"Line {line['lineNumber']}: Existing component '{line['oldPartNumber']}' exists in the released BOM.", f"Released BOM record found: parent={ecn['affectedAssembly']}, component={line['oldPartNumber']}, status=RELEASED.", "The ECN change refers to a valid currently released BOM component."))


def run_checker(data_dir: Path, output_dir: Path) -> Dict[str, Any]:
    parts = _load_parts(data_dir / "parts.csv")
    bom = _load_bom(data_dir / "master_bom.csv")
    headers = _load_headers(data_dir / "ecn_header.csv")
    changes = _load_changes(data_dir / "ecn_changes.csv")

    dashboard_reports = []
    for ecn in headers:
        results = []
        _check_ecn_description(ecn, results)

        ecn_changes = [c for c in changes if c["ecnId"] == ecn["ecnId"]]
        if not ecn_changes:
            results.append(_make_result("BLOCKER", "ECN-002", "No ECN change lines were found", f"No ECN change lines were found for {ecn['ecnId']}", "", "Add at least one BOM change line.", "Add at least one BOM change line."))
            blockers = sum(1 for r in results if r["severity"] == "BLOCKER")
            warnings = sum(1 for r in results if r["severity"] == "WARNING")
            passes = sum(1 for r in results if r["severity"] == "PASS")
            dashboard_reports.append({
                **ecn,
                "results": results,
                "passCount": passes,
                "warningCount": warnings,
                "blockerCount": blockers,
"decision": "BLOCKER" if blockers > 0 else "REVIEW",
            })
            continue

        results.append(_make_result("PASS", "ECN-002", "ECN contains change lines", f"ECN contains {len(ecn_changes)} change line(s)."))

        for line in sorted(ecn_changes, key=lambda item: int(item["lineNumber"])):
            _check_parent_assembly_matches_ecn(ecn, line, results)
            _check_existing_part_in_released_bom(ecn, line, bom, results)

        blockers = sum(1 for r in results if r["severity"] == "BLOCKER")
        warnings = sum(1 for r in results if r["severity"] == "WARNING")
        passes = sum(1 for r in results if r["severity"] == "PASS")
        dashboard_reports.append({
            **ecn,
            "results": results,
            "passCount": passes,
            "warningCount": warnings,
            "blockerCount": blockers,
            "decision": "BLOCKER" if blockers > 0 else "REVIEW",
        })

    dashboard = {"ecns": dashboard_reports}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ecn-dashboard.json").write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    return dashboard