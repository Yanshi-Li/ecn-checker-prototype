"""
Stage 4: Context Engine (RAG-lite)
Compares BOM parts against a reference parts database.
Flags unknown parts, discontinued parts, and quantity anomalies.
Gracefully degrades if no reference data is available.
"""

import logging
import csv
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
DEFAULT_PARTS_DB = ROOT / "data" / "parts_db.csv"


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


def check_historical_conflicts(ecn_id: str, part_number: str, history: list[dict]) -> list[dict]:
    """Return historical ECNs that touched the same part number."""
    key = (ecn_id or "").strip()
    pn = (part_number or "").strip()
    if not pn:
        return []

    conflicts = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        historical_part = str(entry.get("part_number", "")).strip()
        if historical_part != pn:
            continue
        conflicting_ecn = str(entry.get("ecn_id", "")).strip()
        if not conflicting_ecn or conflicting_ecn == key:
            continue
        conflicts.append({
            "conflicting_ecn_id": conflicting_ecn,
            "part_number": pn,
            "status": str(entry.get("status", "")).strip(),
            "date": str(entry.get("date", "")).strip(),
            "change_type": str(entry.get("change_type", "")).strip(),
        })
    return conflicts


# ── Reference data loader ────────────────────────────────────────────────────
def _load_parts_db(filepath: Path) -> dict:
    """
    Load reference parts database into a dict keyed by part_number.
    Returns empty dict if file does not exist.
    """
    if not filepath.exists():
        logger.warning(
            "Parts DB not found at %s — context checks will be skipped.", filepath
        )
        return {}

    parts = {}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pn = row.get("part_number", "").strip()
            if pn:
                parts[pn] = {k.strip().lower(): v.strip() for k, v in row.items()}

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
            pass  # non-numeric quantities already caught by R04

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
def run_context_engine(packet: dict, parts_db_path: Path = DEFAULT_PARTS_DB) -> dict:
    """
    Run context checks against the reference parts database.
    Appends flags to packet['validation']['context_flags'].
    Returns updated packet.
    """
    bom = packet.get("bom", [])
    parts_db = _load_parts_db(parts_db_path)

    all_flags = []

    if not parts_db:
        logger.info(
            "Context Engine: no reference data available — skipping context checks."
        )
        packet["validation"]["context_flags"] = all_flags
        return packet

    all_flags += _check_unknown_parts(bom, parts_db)
    all_flags += _check_part_status_flags(bom, parts_db)
    all_flags += _check_discontinued_parts(bom, parts_db)
    all_flags += _check_quantity_anomalies(bom, parts_db)
    all_flags += _check_description_mismatch(bom, parts_db)

    history = packet.get("history") or []
    ecn_id = packet.get("header", {}).get("ecn_id", "")
    for row in bom:
        pn = row.get("part_number", "").strip()
        if not pn:
            continue
        for conflict in check_historical_conflicts(ecn_id, pn, history):
            all_flags.append({
                "flag_type": "HISTORICAL_CONFLICT",
                "severity": "WARNING",
                "part_number": pn,
                "line_number": row.get("line_number", "?"),
                "message": (
                    f"Part '{pn}' was previously touched by ECN '{conflict['conflicting_ecn_id']}' "
                    f"and may conflict with the current change."
                ),
            })

    packet["validation"]["context_flags"] = all_flags

    error_count = sum(1 for f in all_flags if f["severity"] == "ERROR")
    warn_count = sum(1 for f in all_flags if f["severity"] == "WARNING")
    logger.info(
        "Context Engine complete — %d error(s), %d warning(s)", error_count, warn_count
    )

    return packet