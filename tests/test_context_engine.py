import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from context_engine import (
    check_historical_conflicts,
    check_part_status,
    log_approved_change,
    run_context_engine,
)
from stages.context_engine import _check_missing_supplier, _check_uom_mismatch


MOCK_PARTS = {
    "AB-1001": {"status": "OBSOLETE", "lifecycle_state": "End-of-Life", "revision": "C",
                "description": "Cap 10uF", "part_number": "AB-1001"},
    "AB-1002": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "A",
                "description": "Cap 25V", "part_number": "AB-1002"},
    # New parts from ECN-2026-002 and ECN-2026-003
    "C-350": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "A",
              "description": "Resistor 100 Ohm Low-Cost", "part_number": "C-350"},
    "C-260": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "A",
              "description": "Capacitor 10uF Alternate", "part_number": "C-260"},
    "C-300": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "B",
              "description": "Resistor 100 Ohm", "part_number": "C-300"},
    "C-200": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "A",
              "description": "Capacitor 10uF", "part_number": "C-200"},
}

MOCK_HISTORY = [
    {"ecn_id": "ECN-OLD-001", "part_number": "AB-1001",
     "change_type": "modify", "date": "2023-01-01", "status": "APPROVED"},
    # ECN-2026-002: cost reduction replacing C-300 with C-350
    {"ecn_id": "ECN-2026-002", "part_number": "C-300",
     "change_type": "replace", "date": "2026-10-01", "status": "APPROVED"},
    # ECN-2026-003: stock shortage concession replacing C-200 with C-260
    {"ecn_id": "ECN-2026-003", "part_number": "C-200",
     "change_type": "replace", "date": "2026-11-15", "status": "PENDING"},
]


def test_obsolete_part_detected():
    result = check_part_status("AB-1001", MOCK_PARTS)
    assert result["status"] == "OBSOLETE"
    assert result["found"] is True


def test_active_part_ok():
    result = check_part_status("AB-1002", MOCK_PARTS)
    assert result["status"] == "ACTIVE"


def test_part_not_found():
    result = check_part_status("ZZ-9999", MOCK_PARTS)
    assert result["found"] is False
    assert result["status"] == "NOT_FOUND"


def test_historical_conflict_found():
    conflicts = check_historical_conflicts("ECN-NEW-002", "AB-1001", MOCK_HISTORY)
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_ecn_id"] == "ECN-OLD-001"


def test_no_conflict_same_ecn():
    # Same ECN ID should not conflict with itself
    conflicts = check_historical_conflicts("ECN-OLD-001", "AB-1001", MOCK_HISTORY)
    assert conflicts == []


def test_no_conflict_different_part():
    conflicts = check_historical_conflicts("ECN-NEW-002", "AB-1002", MOCK_HISTORY)
    assert conflicts == []


# ── Tests for new ECN-2026-002 parts ────────────────────────────────────────

def test_c350_active_part_ok():
    result = check_part_status("C-350", MOCK_PARTS)
    assert result["status"] == "ACTIVE"
    assert result["found"] is True


def test_c260_active_part_ok():
    result = check_part_status("C-260", MOCK_PARTS)
    assert result["status"] == "ACTIVE"
    assert result["found"] is True


def test_c300_replaced_by_ecn_2026_002():
    # A new ECN touching C-300 should conflict with ECN-2026-002
    conflicts = check_historical_conflicts("ECN-NEW-999", "C-300", MOCK_HISTORY)
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_ecn_id"] == "ECN-2026-002"


def test_c200_replaced_by_ecn_2026_003():
    # A new ECN touching C-200 should conflict with the pending ECN-2026-003
    conflicts = check_historical_conflicts("ECN-NEW-999", "C-200", MOCK_HISTORY)
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_ecn_id"] == "ECN-2026-003"


def test_ecn_2026_002_no_self_conflict():
    # ECN-2026-002 should not conflict with itself
    conflicts = check_historical_conflicts("ECN-2026-002", "C-300", MOCK_HISTORY)
    assert conflicts == []


def test_ecn_2026_003_no_self_conflict():
    # ECN-2026-003 should not conflict with itself
    conflicts = check_historical_conflicts("ECN-2026-003", "C-200", MOCK_HISTORY)
    assert conflicts == []


def test_missing_supplier_is_flagged_for_known_part():
    bom = [{"line_number": "7", "part_number": "P-100"}]
    parts_db = {"P-100": {"supplier": ""}}

    flags = _check_missing_supplier(bom, parts_db)

    assert flags == [{
        "flag_type": "MISSING_SUPPLIER",
        "severity": "ERROR",
        "part_number": "P-100",
        "line_number": "7",
        "message": "Part 'P-100' has no supplier recorded in the Parts Master DB.",
    }]


def test_missing_supplier_skips_known_part_with_supplier_and_unknown_part():
    bom = [
        {"line_number": "1", "part_number": "P-100"},
        {"line_number": "2", "part_number": "P-999"},
    ]
    parts_db = {"P-100": {"supplier": "Approved Supplier"}}

    assert _check_missing_supplier(bom, parts_db) == []


def test_uom_mismatch_is_flagged_case_insensitively():
    bom = [{"line_number": "4", "part_number": "P-200", "unit": "EA"}]
    parts_db = {"P-200": {"unit_of_measure": "BOX"}}

    flags = _check_uom_mismatch(bom, parts_db)

    assert flags == [{
        "flag_type": "UOM_MISMATCH",
        "severity": "ERROR",
        "part_number": "P-200",
        "line_number": "4",
        "message": "Part 'P-200' unit 'EA' does not match Parts Master DB unit 'BOX'.",
    }]


def test_uom_mismatch_skips_matching_or_blank_units_and_unknown_parts():
    bom = [
        {"line_number": "1", "part_number": "P-200", "unit": "ea"},
        {"line_number": "2", "part_number": "P-300", "unit": ""},
        {"line_number": "3", "part_number": "P-999", "unit": "EA"},
    ]
    parts_db = {
        "P-200": {"unit_of_measure": "EA"},
        "P-300": {"unit_of_measure": "EA"},
    }

    assert _check_uom_mismatch(bom, parts_db) == []


def _csv_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _packet() -> dict:
    return {
        "header": {
            "change_notice_number": "ECN-NEW-CTX-001",
            "change_type": "replace",
            "date": "2026-12-01",
        },
        "bom": [
            {
                "line_number": "1",
                "part_number": "C-300",
                "description": "Resistor 100 Ohm",
                "quantity": "1",
                "unit": "EA",
                "action": "REPLACE",
                "parent_part_no": "DW900",
            },
            {
                "line_number": "2",
                "part_number": "C-350",
                "description": "Resistor 100 Ohm Low-Cost",
                "quantity": "1",
                "unit": "EA",
                "action": "ADD",
                "parent_part_no": "DW900",
            },
        ],
        "validation": {
            "missing_fields": [],
            "rule_violations": [],
            "ai_flags": [],
            "context_flags": [],
        },
    }


def test_context_engine_creates_required_databases(tmp_path):
    packet = _packet()
    root = Path(__file__).parent.parent

    result = run_context_engine(
        packet,
        parts_db_path=root / "data" / "parts_master.csv",
        history_db_path=root / "data" / "ecn_history.csv",
        context_db_dir=tmp_path / "context_db",
    )

    historical_conflicts = [
        flag
        for flag in result["validation"]["context_flags"]
        if flag["flag_type"] == "HISTORICAL_CONFLICT"
    ]
    assert len(historical_conflicts) == 1
    assert historical_conflicts[0]["severity"] == "ERROR"

    artifacts = result["validation"]["context_artifacts"]
    parts_db_path = Path(artifacts["parts_master_database"])
    conflict_log_path = Path(artifacts["ecn_conflict_log"])
    bom_records_path = Path(artifacts["bom_structure_records"])

    assert parts_db_path.exists()
    assert conflict_log_path.exists()
    assert bom_records_path.exists()

    parts_rows = _csv_rows(parts_db_path)
    assert len(parts_rows) == len(_csv_rows(root / "data" / "parts_master.csv"))
    assert set(parts_rows[0]) >= {"supplier", "unit_of_measure"}
    assert len(_csv_rows(conflict_log_path)) == 4  # history seed only; no unapproved run rows
    assert len(_csv_rows(bom_records_path)) == 2





def test_fail_gate_does_not_write_to_conflict_log(tmp_path):
    root = Path(__file__).parent.parent
    context_dir = tmp_path / "context_db"
    packet = run_context_engine(
        _packet(),
        parts_db_path=root / "data" / "parts_master.csv",
        history_db_path=root / "data" / "ecn_history.csv",
        context_db_dir=context_dir,
    )
    packet["gate"] = {"decision": "FAIL"}

    assert log_approved_change(packet) is False
    assert len(_csv_rows(context_dir / "ecn_conflict_log.csv")) == 4


def test_pass_gate_writes_passed_rows_to_conflict_log(tmp_path):
    root = Path(__file__).parent.parent
    context_dir = tmp_path / "context_db"
    packet = run_context_engine(
        _packet(),
        parts_db_path=root / "data" / "parts_master.csv",
        history_db_path=root / "data" / "ecn_history.csv",
        context_db_dir=context_dir,
    )
    packet["gate"] = {"decision": "PASS"}

    assert log_approved_change(packet) is True
    conflict_log_rows = _csv_rows(context_dir / "ecn_conflict_log.csv")
    passed_rows = [row for row in conflict_log_rows if row["source"] == "approved_change"]
    assert len(passed_rows) == 2
    assert {row["status"] for row in passed_rows} == {"PASSED"}