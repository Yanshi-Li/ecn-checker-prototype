"""
Stage 4: Context Engine (RAG-lite)
Compares BOM parts against a reference parts database.
Flags unknown parts, discontinued parts, missing suppliers, UoM mismatches, and quantity anomalies.
Also persists context test databases/logs for repeatable module testing.
"""

import csv
import logging
import re

from datetime import datetime, timezone
from pathlib import Path

from scripts.rule_catalogue import rules_for_engine

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_PARTS_DB = DATA_DIR / "Part_Master.csv"
DEFAULT_ECN_HISTORY_DB = DATA_DIR / "ecn_history.csv"
DEFAULT_CONTEXT_DB_DIR = ROOT / "out" / "context_engine"


ECN_CONFLICT_LOG_FILENAME = "change_notice_log.csv"
BOM_STRUCTURE_RECORDS_FILENAME = "bom_structure_records.csv"
CONFLICT_LOG_FIELDNAMES = [
    "logged_at",
    "source",
    "change_notice_number",
    "part_number",
    "change_type",
    "date",
    "status",
]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv_rows(filepath: Path) -> list[dict]:
    """Read CSV rows and normalize the external Change Notice Number heading."""
    if not filepath.exists():
        logger.warning("CSV source not found at %s", filepath)
        return []

    rows = []
    with open(filepath, newline="", encoding="utf-8") as file_handle:
        for row in csv.DictReader(file_handle):
            normalized_row = {}
            for key, value in row.items():
                clean_key = str(key or "").strip()
                if not clean_key:
                    continue
                canonical_key = (
                    "change_notice_number"
                    if clean_key.casefold() == "change notice number"
                    else clean_key
                )
                normalized_row[canonical_key] = str(value or "").strip()
            if normalized_row:
                rows.append(normalized_row)
    return rows



def _append_csv_rows(filepath: Path, fieldnames: list[str], rows: list[dict]) -> None:
    if not rows:
        return

    filepath.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not filepath.exists()
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if should_write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})





def _resolve_parts_source(parts_source_path: Path | None) -> Path:
    """Return the supplied parts master or the checked-in reference file."""
    return Path(parts_source_path) if parts_source_path is not None else DEFAULT_PARTS_DB



def create_context_databases(
    packet: dict,
    parts_source_path: Path | None = None,
    history_source_path: Path | None = None,
    context_db_dir: Path = DEFAULT_CONTEXT_DB_DIR,
) -> dict:
    """Create audit artifacts while using the parts master source in place."""
    parts_source = _resolve_parts_source(parts_source_path)
    history_source = Path(history_source_path) if history_source_path else DEFAULT_ECN_HISTORY_DB
    output_dir = Path(context_db_dir)
    ecn_conflict_log_path = output_dir / ECN_CONFLICT_LOG_FILENAME
    bom_structure_records_path = output_dir / BOM_STRUCTURE_RECORDS_FILENAME
    run_timestamp = _now_utc_iso()

    if not ecn_conflict_log_path.exists():
        history_seed_rows = [
            {
                "logged_at": run_timestamp,
                "source": "history_seed",
                "change_notice_number": row.get("change_notice_number", "").strip(),
                "part_number": row.get("part_number", "").strip(),
                "change_type": row.get("change_type", "").strip(),
                "date": row.get("date", "").strip(),
                "status": row.get("status", "").strip(),
            }
            for row in _read_csv_rows(history_source)
            if row.get("part_number", "").strip()
        ]
        _append_csv_rows(ecn_conflict_log_path, CONFLICT_LOG_FIELDNAMES, history_seed_rows)

    change_notice_number = (
        str(packet.get("header", {}).get("change_notice_number", "")).strip()
        or "UNKNOWN_ECN"
    )
    bom_fieldnames = [
        "logged_at", "change_notice_number", "line_number", "part_number", "description",
        "quantity", "unit", "action", "parent_part_no",
    ]
    bom_structure_rows = [
        {
            "logged_at": run_timestamp,
            "change_notice_number": change_notice_number,
            "line_number": str(row.get("line_number", "")).strip(),
            "part_number": str(row.get("part_number", "")).strip(),
            "description": str(row.get("description", "")).strip(),
            "quantity": str(row.get("quantity", "")).strip(),
            "unit": str(row.get("unit", "")).strip(),
            "action": str(row.get("action", "")).strip(),
            "parent_part_no": str(row.get("parent_part_no", "")).strip(),
        }
        for row in packet.get("bom", [])
        if str(row.get("part_number", "")).strip()
    ]
    _append_csv_rows(bom_structure_records_path, bom_fieldnames, bom_structure_rows)
    logger.info(
        "Context artifacts ready — parts source:%s bom_records:+%d",
        parts_source,
        len(bom_structure_rows),
    )
    return {
        "parts_master_source": str(parts_source),
        "ecn_conflict_log": str(ecn_conflict_log_path),
        "bom_structure_records": str(bom_structure_records_path),
    }




def log_approved_change(packet: dict) -> bool:
    """Persist BOM parts to the conflict log only for a final PASS decision."""
    if packet.get("gate", {}).get("decision") != "PASS":
        logger.info("Conflict log unchanged because gate decision is not PASS.")
        return False

    conflict_log = packet.get("validation", {}).get("context_artifacts", {}).get(
        "ecn_conflict_log"
    )
    if not conflict_log:
        logger.warning("Cannot log approved change: context conflict-log artifact is missing.")
        return False

    header = packet.get("header", {})
    change_notice_number = str(header.get("change_notice_number", "")).strip() or "UNKNOWN_ECN"
    approved_rows = [
        {
            "logged_at": _now_utc_iso(),
            "source": "approved_change",
            "change_notice_number": change_notice_number,
            "part_number": str(row.get("part_number", "")).strip(),
            "change_type": str(row.get("action", "")).strip() or str(header.get("change_type", "")).strip(),
            "date": str(header.get("date", "")).strip(),
            "status": "PASSED",
        }
        for row in packet.get("bom", [])
        if str(row.get("part_number", "")).strip()
    ]
    _append_csv_rows(Path(conflict_log), CONFLICT_LOG_FIELDNAMES, approved_rows)
    logger.info("Conflict log recorded %d passed BOM part(s).", len(approved_rows))
    return bool(approved_rows)



def check_part_status(part_number: str, parts_db: dict) -> dict:
    """Return normalized status information for a part number."""
    key = (part_number or "").strip()
    if not key:
        return {
            "part_number": key,
            "status": "NOT_FOUND",
            "found": False,
            "lifecycle_state": None,
            "revision": None,
            "description": None,
        }

    record = parts_db.get(key)
    if not record:
        return {
            "part_number": key,
            "status": "NOT_FOUND",
            "found": False,
            "lifecycle_state": None,
            "revision": None,
            "description": None,
        }

    normalized = {str(k).strip().lower(): v for k, v in record.items()}
    raw_status = str(
        normalized.get("status")
        or normalized.get("lifecycle_status")
        or normalized.get("lifecyclestate")
        or ""
    ).strip().upper()
    lifecycle_state = (
        normalized.get("lifecycle_state")
        or normalized.get("lifecycleState")
        or normalized.get("lifecycle_status")
        or ""
    ).strip()
    result = {
        "part_number": key,
        "status": raw_status or "ACTIVE",
        "found": True,
        "lifecycle_state": lifecycle_state,
        "revision": (normalized.get("revision") or "").strip(),
        "description": (normalized.get("description") or "").strip(),
    }
    if raw_status in {"OBSOLETE", "DISCONTINUED", "ON_HOLD", "HOLD"}:
        result["status"] = "OBSOLETE"
    return result





# ── Reference data loader ────────────────────────────────────────────────────
def _canonical_part_column(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().casefold()).strip("_")
    aliases = {
        "partnumber": "part_number",
        "part_number": "part_number",
        "unit_measure": "unit_of_measure",
        "unit_of_measure": "unit_of_measure",
        "primary_role": "primary_role",
        "lifecycle_state": "lifecycle_state",
        "lifecycle_status": "lifecycle_status",
    }
    return aliases.get(normalized, normalized)


def _load_parts_db(filepath: Path) -> dict:
    """
    Load a parts master CSV, including the report-style Part_Master.csv format.

    The checked-in reference file has a report title row before a human-readable
    header (for example, ``Part Number`` and ``Unit Measure``). The loader finds
    that header and normalizes its column names to the fields used by the checks.
    """
    if not filepath.exists():
        logger.warning(
            "Parts DB not found at %s — context checks will be skipped.", filepath
        )
        return {}

    with open(filepath, newline="", encoding="utf-8-sig") as file_handle:
        csv_rows = list(csv.reader(file_handle))

    header_index = next(
        (
            index
            for index, row in enumerate(csv_rows)
            if any(_canonical_part_column(cell) == "part_number" for cell in row)
        ),
        None,
    )
    if header_index is None:
        logger.warning("Parts DB at %s has no Part Number column.", filepath)
        return {}

    headers = [_canonical_part_column(cell) for cell in csv_rows[header_index]]
    parts = {}
    for values in csv_rows[header_index + 1 :]:
        if not any(value.strip() for value in values):
            continue
        row = {
            header: (values[index] if index < len(values) else "").strip()
            for index, header in enumerate(headers)
            if header
        }
        pn = row.get("part_number", "")
        if not pn:
            continue

        # The report uses Primary Role/Class instead of a status column.
        if "status" not in row:
            role = row.get("primary_role", "").casefold()
            part_class = row.get("class", "").casefold()
            if role == "ob" or "obsolete" in part_class:
                row["status"] = "OBSOLETE"
            elif role:
                row["status"] = "ACTIVE"
        parts[pn] = row

    logger.info("Parts DB loaded: %d parts from %s", len(parts), filepath)
    return parts



# ── Context checks ────────────────────────────────────────────────────────────
def _check_unknown_parts(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag BOM parts not found in the reference parts database."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        if pn and pn not in parts_db:
            flags.append({
                "flag_type": "UNKNOWN_PART",
                "severity": "WARNING",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": f"Part '{pn}' on line {row.get('line_number', '?')} "
                           f"is not in the reference parts database.",
            })
    return flags


def _check_part_status_flags(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag parts with inactive status or lifecycle blocks."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        if not pn:
            continue
        status = check_part_status(pn, parts_db)
        if not status["found"]:
            continue
        if status["status"] in {"OBSOLETE", "DISCONTINUED", "ON_HOLD", "HOLD"}:
            flags.append({
                "flag_type": "DISCONTINUED_PART",
                "severity": "ERROR",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": f"Part '{pn}' is marked as {status['status']} and cannot be used in a new ECN.",
            })
    return flags


def _check_discontinued_parts(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag BOM parts marked as discontinued in the reference database."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        ref = parts_db.get(pn, {})
        status = ref.get("status", "").strip().lower()
        if status in ("discontinued", "obsolete"):
            flags.append({
                "flag_type": "DISCONTINUED_PART",
                "severity": "ERROR",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": f"Part '{pn}' on line {row.get('line_number', '?')} "
                           f"is marked as '{status}' in the reference database.",
            })
    return flags


def _check_missing_supplier(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag known EBOM parts that have no supplier in the reference database."""
    flags = []
    for row in bom:
        if str(row.get("bom_type", "")).strip().upper() != "EBOM":
            continue

        pn = row.get("part_number", "").strip()
        ref = parts_db.get(pn)
        if pn and ref is not None and not ref.get("supplier", "").strip():
            flags.append({
                "rule_id": "D03",
                "flag_type": "MISSING_SUPPLIER",
                "severity": "ERROR",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": f"Part '{pn}' has no supplier recorded in the Parts Master DB.",
            })
    return flags



def _check_uom_mismatch(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag known BOM parts whose unit differs from the reference database."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        ref = parts_db.get(pn)
        bom_unit = row.get("unit", "").strip()
        db_unit = ref.get("unit_of_measure", "").strip() if ref else ""
        if pn and ref is not None and bom_unit and db_unit and bom_unit.lower() != db_unit.lower():
            flags.append({
                "flag_type": "UOM_MISMATCH",
                "severity": "ERROR",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": (
                    f"Part '{pn}' unit '{bom_unit}' does not match Parts Master DB unit "
                    f"'{db_unit}'."
                ),
            })
    return flags


def _check_quantity_anomalies(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag BOM lines where quantity exceeds the reference max quantity."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        ref = parts_db.get(pn, {})
        max_qty_raw = ref.get("max_quantity", "").strip()
        qty_raw = row.get("quantity", "").strip()

        if not max_qty_raw or not qty_raw:
            continue

        try:
            qty = float(qty_raw)
            max_qty = float(max_qty_raw)
            if qty > max_qty:
                flags.append({
                    "flag_type": "QUANTITY_ANOMALY",
                    "severity": "WARNING",
                    "part_number": pn,
                    "line_number": row.get("line_number", "?"),
                    "message": f"Part '{pn}' on line {row.get('line_number', '?')} "
                               f"has quantity {qty} exceeding reference max of {max_qty}.",
                })
        except ValueError:
            pass  # non-numeric quantities are handled by the active quantity rule

    return flags


def _check_description_mismatch(bom: list[dict], parts_db: dict) -> list[dict]:
    """Flag BOM lines where description does not match the reference description."""
    flags = []
    for row in bom:
        pn = row.get("part_number", "").strip()
        ref = parts_db.get(pn, {})
        ref_desc = ref.get("description", "").strip().lower()
        bom_desc = row.get("description", "").strip().lower()

        if ref_desc and bom_desc and ref_desc != bom_desc:
            flags.append({
                "flag_type": "DESCRIPTION_MISMATCH",
                "severity": "WARNING",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": f"Part '{pn}' description '{bom_desc}' does not match "
                           f"reference '{ref_desc}'.",
            })
    return flags


# ── Public entry point ────────────────────────────────────────────────────────
def run_context_engine(
    packet: dict,
    parts_db_path: Path | None = None,
    history_db_path: Path | None = None,
    context_db_dir: Path = DEFAULT_CONTEXT_DB_DIR,
) -> dict:
    """
    Run context checks against the reference parts database.
    Also materializes context-engine data files used during module testing.
    Appends flags to packet['validation']['context_flags'].
        Returns updated packet.
    """
    configured_rules = rules_for_engine("context_engine")
    logger.info(
        "Context Engine catalogue mapping: %d reference-data rule(s).",
        len(configured_rules),
    )

    bom = packet.get("bom", [])
    artifacts = create_context_databases(
        packet=packet,
        parts_source_path=parts_db_path,
        history_source_path=history_db_path,
        context_db_dir=context_db_dir,
    )

        
    parts_db = _load_parts_db(Path(artifacts["parts_master_source"]))


    

    all_flags = []

    if not parts_db:
        logger.info(
            "Context Engine: no reference data available — skipping context checks."
        )
        packet["validation"]["context_flags"] = all_flags
        packet["validation"]["context_artifacts"] = artifacts
        return packet

    all_flags += _check_unknown_parts(bom, parts_db)
    all_flags += _check_part_status_flags(bom, parts_db)
    all_flags += _check_discontinued_parts(bom, parts_db)
    all_flags += _check_missing_supplier(bom, parts_db)
    all_flags += _check_uom_mismatch(bom, parts_db)
    all_flags += _check_quantity_anomalies(bom, parts_db)
    all_flags += _check_description_mismatch(bom, parts_db)

    


    packet["validation"]["context_flags"] = all_flags; packet["validation"]["context_artifacts"] = artifacts


    error_count = sum(1 for f in all_flags if f["severity"] == "ERROR")
    warn_count = sum(1 for f in all_flags if f["severity"] == "WARNING")
    logger.info(
        "Context Engine complete — %d error(s), %d warning(s), flag types: %s",
        error_count,
        warn_count,
        sorted({flag["flag_type"] for flag in all_flags}),
    )

    return packet
