import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from context_engine import (
    check_part_status,
    check_historical_conflicts,
    run_context_engine,
)


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


def _csv_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _packet() -> dict:
    return {
        "header": {
            "ecn_id": "ECN-NEW-CTX-001",
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

    artifacts = result["validation"]["context_artifacts"]
    parts_db_path = Path(artifacts["parts_master_database"])
    conflict_log_path = Path(artifacts["ecn_conflict_log"])
    bom_records_path = Path(artifacts["bom_structure_records"])

    assert parts_db_path.exists()
    assert conflict_log_path.exists()
    assert bom_records_path.exists()

    assert len(_csv_rows(parts_db_path)) == 3
    assert len(_csv_rows(conflict_log_path)) == 6  # 4 seeded history rows + 2 test BOM rows
    assert len(_csv_rows(bom_records_path)) == 2


def test_context_logs_append_for_each_test_run(tmp_path):
    root = Path(__file__).parent.parent
    context_dir = tmp_path / "context_db"

    run_context_engine(
        _packet(),
        parts_db_path=root / "data" / "parts_master.csv",
        history_db_path=root / "data" / "ecn_history.csv",
        context_db_dir=context_dir,
    )
    run_context_engine(
        _packet(),
        parts_db_path=root / "data" / "parts_master.csv",
        history_db_path=root / "data" / "ecn_history.csv",
        context_db_dir=context_dir,
    )

    conflict_log_rows = _csv_rows(context_dir / "ecn_conflict_log.csv")
    bom_structure_rows = _csv_rows(context_dir / "bom_structure_records.csv")

    assert len(conflict_log_rows) == 8  # 4 seeded history rows + 2 runs * 2 BOM rows
    assert len(bom_structure_rows) == 4  # 2 runs * 2 BOM rows