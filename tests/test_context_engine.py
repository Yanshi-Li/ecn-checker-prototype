import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from context_engine import check_part_status, check_historical_conflicts


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